"""Extracts Spring MVC HTTP routes from raw Java source, using our own
FTS5-backed search over full file text (not GitNexus's graph, which drops
annotation usage sites entirely — see MCPProtocol/ToolDesign notes for why).
"""
import hashlib
import logging
import os
import re
import sqlite3
import time
from dataclasses import dataclass

# stdio类型的MCP Server里，stdout留给JSON-RPC消息用，日志只能走stderr——
# logging模块默认就是输出到stderr，这里不用print()就是为了这个
logger = logging.getLogger(__name__)

# 建索引/扫描时跳过的目录：构建产物、VCS元数据、IDE配置——不是源码
SKIP_DIRS = {".git", "target", "build", ".idea", "node_modules", ".gitnexus"}

# FTS5索引缓存放在我们自己工具的缓存目录下，不写进目标仓库里——
# 我们对被扫描的仓库只假设有读权限，不该往里面塞自己的文件
CACHE_DIR = os.path.expanduser("~/.cache/api-impact-tool/route-index")

METHOD_ANNOTATION_TO_HTTP = {
    "GetMapping": "GET",
    "PostMapping": "POST",
    "PutMapping": "PUT",
    "DeleteMapping": "DELETE",
    "PatchMapping": "PATCH",
}
MAPPING_ANNOTATION_NAMES = ["RequestMapping"] + list(METHOD_ANNOTATION_TO_HTTP)

# 匹配单行注解，比如 @PostMapping(value = "/x") 或裸的 @GetMapping。
# group(1) = 注解名；group(2) = 括号里的全部内容（没有括号则是None）。
ANNOTATION_RE = re.compile(
    r"@(" + "|".join(MAPPING_ANNOTATION_NAMES) + r")\b(?:\s*\(([^)]*)\))?"
)

# 注解参数里第一个双引号字符串——不管是位置参数("/x")还是命名参数(value="/x"/path="/x")，
# 路径永远是括号里出现的第一个字符串字面量
FIRST_STRING_LITERAL_RE = re.compile(r'"([^"]*)"')

# 通用@RequestMapping专用：从method = RequestMethod.POST这种写法里，把HTTP动词抠出来
METHOD_VERB_RE = re.compile(r"method\s*=\s*RequestMethod\.(\w+)")

# Java方法声明行：<修饰符> <返回类型> methodName( —— 只需要抓紧跟在"("前面的那个标识符
METHOD_NAME_RE = re.compile(r"(\w+)\s*\(")


@dataclass(frozen=True)
class RouteRecord:
    """One HTTP route, resolved to the class+method that handles it.

    http_method: "GET" / "POST" / etc., uppercase, OR "ANY" when neither the class
        nor the method specifies a method= restriction — per Spring's own runtime
        source (RequestMethodsRequestCondition: "if 0 [methods], the condition
        will match to every request"), this is a real, well-defined route that
        accepts every HTTP method, not an ambiguous case to be dropped.
    url: fully composed path (class-level @RequestMapping prefix + method-level
         path, if any). Always starts with "/".
    class_name: simple class name (no package), e.g. "PromotionController".
    method_name: the handler method's name, e.g. "comparePrice".
    file_path: path relative to the repo root.
    line_number: 1-based line of the method-level mapping annotation.
    pattern: which annotation shape produced this record —
        "explicit_value"                    e.g. @PostMapping("/x") or @PostMapping(value="/x")
        "bare_inherits_prefix"              e.g. @GetMapping with no arguments at all
        "request_mapping_with_method"       e.g. @RequestMapping(value="/x", method=RequestMethod.POST)
        "request_mapping_inherits_class_method"
            e.g. @RequestMapping("/x") on a method with no method= of its own,
            while the class-level @RequestMapping does specify one — inherited
            per Spring's own javadoc ("all method-level mappings inherit this
            HTTP method restriction").
        "request_mapping_no_restriction"
            neither the class nor the method specifies method= anywhere — http_method is "ANY".
    """
    http_method: str
    url: str
    class_name: str
    method_name: str
    file_path: str
    line_number: int
    pattern: str


def _iter_java_files(repo_path):
    """遍历repo_path下所有.java文件，跳过SKIP_DIRS里列的构建产物/VCS目录。
    每次产出 (相对路径, 绝对路径) 这样一对。
    """
    for root, dirs, files in os.walk(repo_path):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for name in files:
            if name.endswith(".java"):
                full = os.path.join(root, name)
                yield os.path.relpath(full, repo_path), full


def _cache_db_path(repo_path: str) -> str:
    """这个仓库对应的缓存索引文件该放在哪。用绝对路径的hash做文件名后缀，
    避免两个不同目录但同名（比如两个不同项目都叫"api"）的仓库互相覆盖缓存。
    """
    os.makedirs(CACHE_DIR, exist_ok=True)
    abs_repo = os.path.abspath(repo_path)
    digest = hashlib.sha256(abs_repo.encode("utf-8")).hexdigest()[:16]
    safe_name = os.path.basename(abs_repo.rstrip("/")) or "repo"
    return os.path.join(CACHE_DIR, f"{safe_name}-{digest}.db")


def _current_file_mtimes(repo_path: str) -> dict:
    """只做stat()拿修改时间，不读文件内容——用来快速判断缓存是否还新鲜，
    这一步哪怕仓库有几千个文件也很快，跟"读全文建索引"完全是两个数量级的开销。
    """
    return {
        rel_path: os.path.getmtime(full_path)
        for rel_path, full_path in _iter_java_files(repo_path)
    }


def _load_cached_mtimes(conn: sqlite3.Connection):
    """读缓存文件里记录的、上次建索引时每个文件的mtime快照。
    缓存文件是全新的（表还没建过）时返回None，跟"有记录但是空仓库"区分开。
    """
    try:
        cur = conn.execute("SELECT rel_path, mtime FROM _index_meta")
        return dict(cur.fetchall())
    except sqlite3.OperationalError:
        return None


def _build_fts_index(repo_path: str) -> sqlite3.Connection:
    """建一份持久化到磁盘的SQLite FTS5索引，把repo_path下每个.java文件的原始全文
    整个塞进去（不是GitNexus那种按符号切片的content，是完整文件文本，注解行不会丢）。

    带缓存：如果上次建索引之后，仓库里所有.java文件的路径集合和mtime都没变，
    直接复用磁盘上已有的索引文件，不重新读盘、不重新插入FTS5——这对大仓库（比如
    几百MB的health_capi）意义很大，小项目差别不明显但机制先建好。

    调用方用完后自己负责关闭这个连接。
    """
    start = time.perf_counter()
    cache_path = _cache_db_path(repo_path)
    current_mtimes = _current_file_mtimes(repo_path)

    if os.path.isfile(cache_path):
        conn = sqlite3.connect(cache_path)
        cached_mtimes = _load_cached_mtimes(conn)
        if cached_mtimes == current_mtimes:
            elapsed = time.perf_counter() - start
            logger.info(
                "FTS5索引命中缓存：%d个文件，校验耗时%.3fs（repo=%s，cache=%s）",
                len(current_mtimes), elapsed, repo_path, cache_path,
            )
            return conn
        conn.close()
        os.remove(cache_path)  # 文件集合或mtime变了，缓存作废，重新建一份

    conn = sqlite3.connect(cache_path)
    conn.execute(
        "CREATE VIRTUAL TABLE files_fts USING fts5(path UNINDEXED, body, tokenize='unicode61')"
    )
    conn.execute("CREATE TABLE _index_meta (rel_path TEXT PRIMARY KEY, mtime REAL)")

    read_start = time.perf_counter()
    rows = []
    for rel_path, full_path in _iter_java_files(repo_path):
        with open(full_path, "r", encoding="utf-8", errors="replace") as f:
            body = f.read()
        rows.append((rel_path, body))
    read_elapsed = time.perf_counter() - read_start

    insert_start = time.perf_counter()
    conn.executemany("INSERT INTO files_fts(path, body) VALUES (?, ?)", rows)
    conn.executemany(
        "INSERT INTO _index_meta(rel_path, mtime) VALUES (?, ?)",
        list(current_mtimes.items()),
    )
    conn.commit()
    insert_elapsed = time.perf_counter() - insert_start

    total_elapsed = time.perf_counter() - start
    logger.info(
        "FTS5索引全量重建：%d个文件，读盘%.3fs + 插入索引%.3fs，总耗时%.3fs（repo=%s，cache=%s）",
        len(rows), read_elapsed, insert_elapsed, total_elapsed, repo_path, cache_path,
    )
    return conn


def _find_candidate_files(conn: sqlite3.Connection):
    """FTS5查询：先快速筛出"哪些文件里提到了任意一个Spring路由注解"，
    把可能几百上千个文件的仓库，缩小到只剩几个候选文件，再做后面的正则解析——
    避免对整个仓库逐字节做正则扫描。
    """
    query = " OR ".join(MAPPING_ANNOTATION_NAMES)
    cur = conn.execute(
        "SELECT path, body FROM files_fts WHERE files_fts MATCH ?", (query,)
    )
    return cur.fetchall()


def _extract_class_name(file_path: str) -> str:
    """Java规定：一个文件里的public顶层类，类名必须跟文件名（去掉.java后缀）相同。
    直接从文件名拿类名，比在文件内容里正则猜"class后面那个词是不是它"更可靠——
    这也是_find_class_declaration_index能精确定位类声明位置的依据。
    """
    return os.path.splitext(os.path.basename(file_path))[0]


def _find_class_declaration_index(body: str, class_name: str):
    """定位真正的类声明（`class WidgetController`这一段）在文件里的字符位置。

    这个位置是判断"某个@XxxMapping到底修饰的是类还是方法"的可靠依据：
    Java语法要求所有方法都写在类体内部，也就是class声明这个位置之后——
    所以任何出现在这个位置之前的路由注解，物理上不可能是方法上的注解，
    只可能是修饰这个类本身的（class自己的字段/内部类不会被误伤，因为它们本来就不会
    出现在class关键字之前）。
    比之前那条"没有method=参数就当作class前缀"的推断规则更可靠——
    Spring官方文档证实class级别的@RequestMapping完全可以合法地带method=参数
    （见ToolDesign.md记录的那次修正），带不带method=不能用来判断层级。

    这条正则要求"class 类名"必须出现在**行首**（前面最多跟着public/private/
    abstract/final这类修饰符），不能出现在一行的中间——真正的类声明永远长这样，
    但javadoc注释（"* ...similar to class WidgetController..."）或字符串字面量
    里巧合提到"class 类名"这几个字，几乎不可能凑巧也出现在行首紧跟着这几个
    修饰符关键字，这样就把注释/字符串里的巧合排除掉了。
    """
    modifiers = r"(?:public\s+|private\s+|protected\s+|abstract\s+|final\s+|static\s+)*"
    pattern = r"(?:^|\n)[ \t]*" + modifiers + r"class\s+" + re.escape(class_name) + r"\b"
    match = re.search(pattern, body)
    if not match:
        return None
    # match.start()在多行模式下可能落在"\n"这个字符本身上，往前挪到真正的
    # 修饰符/class关键字开始的地方（去掉这一步不影响正确性，只是为了让
    # 返回的位置更精确，方便调试时肉眼核对）
    return match.end() - len(match.group().lstrip("\n"))


def _extract_class_prefix(body: str, class_index):
    """找这个文件里class级别的@RequestMapping前缀（如果有的话）——
    只看出现在class_index之前的@RequestMapping，不管它带不带method=参数。
    """
    if class_index is None:
        return None
    for match in ANNOTATION_RE.finditer(body):
        if match.start() >= class_index:
            break  # 已经扫过类声明的位置了，后面全是方法级别的注解，不用再看
        name, args = match.group(1), match.group(2)
        if name != "RequestMapping":
            continue
        literal = FIRST_STRING_LITERAL_RE.search(args or "")
        if literal:
            return literal.group(1)
    return None


def _extract_class_method(body: str, class_index):
    """找这个文件里class级别@RequestMapping的method=限定（如果写了的话）。

    依据Spring官方RequestMapping.method()的javadoc："Supported at the type level
    as well as at the method level! When used at the type level, all method-level
    mappings inherit this HTTP method restriction."——class级别的method=会被这个
    class下所有没自己指定method=的方法级别映射继承，不是只在方法级别才有意义。

    返回None代表"class级别没有method=限定"，调用方要在这基础上再自己判断
    "方法自己有没有method="，两级都没有的话就是Spring运行时确认过的
    "接受所有HTTP方法"（不是随便挑一个默认值）。
    """
    if class_index is None:
        return None
    for match in ANNOTATION_RE.finditer(body):
        if match.start() >= class_index:
            break
        name, args = match.group(1), match.group(2)
        if name != "RequestMapping" or args is None:
            continue
        verb_match = METHOD_VERB_RE.search(args)
        if verb_match:
            return verb_match.group(1)
    return None


def _find_method_name_after(lines: list[str], annotation_line_index: int):
    """从注解自己所在的那一行开始往下找，跳过空行、堆叠在同一个方法上的其他注解、
    以及可能夹在中间的javadoc/块注释，找到真正的方法声明行，抠出方法名。

    安全阀：跳过所有"确定不是代码"的行之后，遇到的第一行真实代码如果还是不匹配
    方法声明的样子，直接放弃（返回None），不会继续往下瞎找——避免在扫描窗口更远
    处误配到一个不相关的方法名，把明确的失败变成一个看似合理但其实关联错了的结果。

    返回 (方法名, 行号)；找不到则返回 (None, None)。
    """
    in_block_comment = False
    for offset in range(0, 10):
        idx = annotation_line_index + offset
        if idx >= len(lines):
            break
        line = lines[idx].strip()

        if in_block_comment:
            if "*/" in line:
                in_block_comment = False
            continue

        if not line or line.startswith("@") or line.startswith("//"):
            continue
        if line.startswith("/*"):  # 覆盖 /** 和 /* 两种块注释开头
            if "*/" not in line:  # 没在同一行闭合，说明是跨行的javadoc/块注释
                in_block_comment = True
            continue
        if line.startswith("*"):  # javadoc块注释内部的延续行
            continue

        match = METHOD_NAME_RE.search(line)
        if match:
            return match.group(1), idx + 1  # 转成1-based行号
        break
    return None, None


def _classify_and_extract(
    rel_path: str, body: str, class_name, class_prefix, class_index, class_method
) -> list[RouteRecord]:
    lines = body.splitlines()
    records = []
    for match in ANNOTATION_RE.finditer(body):
        if class_index is not None and match.start() < class_index:
            continue  # 类声明之前的注解是修饰类本身的，不是方法路由（见_find_class_declaration_index）

        name, args = match.group(1), match.group(2)
        annotation_line_index = body.count("\n", 0, match.start())

        if name == "RequestMapping":
            verb_match = METHOD_VERB_RE.search(args) if args is not None else None
            if verb_match:
                # 方法自己写了method=，正常情况
                verb = verb_match.group(1)
                pattern = "request_mapping_with_method"
            elif class_method is not None:
                # 方法自己没写method=，但class级别有限定——按Spring官方javadoc
                # ("all method-level mappings inherit this HTTP method restriction")
                # 继承class的动词，不能因为方法自己没写就跳过
                verb = class_method
                pattern = "request_mapping_inherits_class_method"
            else:
                # class和方法两级都没有method=限定——依据RequestMethodsRequestCondition
                # 的运行时源码，这是明确定义的"接受所有HTTP方法"，不是该跳过的模糊情况
                verb = "ANY"
                pattern = "request_mapping_no_restriction"
            literal = FIRST_STRING_LITERAL_RE.search(args or "")
            path = literal.group(1) if literal else ""
        else:
            verb = METHOD_ANNOTATION_TO_HTTP[name]
            literal = FIRST_STRING_LITERAL_RE.search(args or "")
            path = literal.group(1) if literal else ""
            pattern = "explicit_value" if path else "bare_inherits_prefix"

        method_name, line_number = _find_method_name_after(lines, annotation_line_index)
        if method_name is None:
            continue

        prefix = (class_prefix or "").rstrip("/")
        if not path:
            suffix = ""
        elif path.startswith("/"):
            suffix = path
        else:
            suffix = "/" + path
        url = (prefix + suffix) or "/"

        records.append(
            RouteRecord(
                http_method=verb,
                url=url,
                class_name=class_name or "?",
                method_name=method_name,
                file_path=rel_path,
                line_number=line_number,
                pattern=pattern,
            )
        )
    return records


def extract_routes(repo_path: str) -> list[RouteRecord]:
    """扫描repo_path，返回找到的所有Spring MVC路由。

    流程：① 建一次性FTS5全文索引 → ② 用FTS5快速筛出提到路由注解的候选文件
    → ③ 对候选文件逐个做正则解析，拼出完整URL。
    """
    conn = _build_fts_index(repo_path)
    try:
        candidates = _find_candidate_files(conn)
    finally:
        conn.close()

    all_routes = []
    for rel_path, body in candidates:
        class_name = _extract_class_name(rel_path)
        class_index = _find_class_declaration_index(body, class_name)
        class_prefix = _extract_class_prefix(body, class_index)
        class_method = _extract_class_method(body, class_index)
        all_routes.extend(
            _classify_and_extract(
                rel_path, body, class_name, class_prefix, class_index, class_method
            )
        )
    return all_routes
