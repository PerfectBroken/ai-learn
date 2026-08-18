"""FTS5索引缓存机制的测试——用一个独立的临时目录，不动promotion-api真实项目的文件。

目标行为：
1. 第一次调用：没有缓存，全量建索引，并把索引文件持久化到磁盘（不是:memory:）
2. 第二次调用（源文件没变）：命中缓存，不重新读盘、不重新建索引
3. 改动了某个源文件之后再调用：检测到过期，重新全量建索引，拿到的结果反映最新内容
"""
import logging
import os
import time

import pytest

import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from route_extractor import _build_fts_index, _cache_db_path

CONTROLLER_TEMPLATE = """\
package demo;

import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/demo")
public class DemoController {{

    @GetMapping("/{path}")
    public String ping() {{
        return "ok";
    }}
}}
"""


@pytest.fixture
def tiny_repo(tmp_path):
    """一个只有一个Controller的最小仓库，专门用来测缓存行为，不测路由解析的正确性
    （路由解析正确性由test_route_extractor.py对着真实的promotion-api项目负责）。
    """
    controller_file = tmp_path / "DemoController.java"
    controller_file.write_text(CONTROLLER_TEMPLATE.format(path="ping"))
    return tmp_path


def test_first_call_persists_index_to_disk(tiny_repo, caplog):
    caplog.set_level(logging.INFO)
    conn = _build_fts_index(str(tiny_repo))
    conn.close()

    cache_path = _cache_db_path(str(tiny_repo))
    assert os.path.isfile(cache_path), "第一次调用应该把索引落盘，不是只存在内存里"
    assert "全量重建" in caplog.text


def test_second_call_without_changes_hits_cache(tiny_repo, caplog):
    conn = _build_fts_index(str(tiny_repo))
    conn.close()

    caplog.clear()
    caplog.set_level(logging.INFO)
    conn = _build_fts_index(str(tiny_repo))
    conn.close()

    assert "命中缓存" in caplog.text, f"应该命中缓存，实际日志：{caplog.text}"
    assert "全量重建" not in caplog.text


def test_modifying_a_file_invalidates_the_cache(tiny_repo, caplog):
    conn = _build_fts_index(str(tiny_repo))
    conn.close()

    # 改动源文件内容，并确保mtime真的往前走了（有些文件系统时间戳精度是1秒，
    # 睡一下避免"改了但mtime没变"导致测试假失败）
    time.sleep(1.1)
    controller_file = tiny_repo / "DemoController.java"
    controller_file.write_text(CONTROLLER_TEMPLATE.format(path="pong"))

    caplog.clear()
    caplog.set_level(logging.INFO)
    conn = _build_fts_index(str(tiny_repo))
    cur = conn.execute("SELECT body FROM files_fts")
    bodies = [row[0] for row in cur.fetchall()]
    conn.close()

    assert "全量重建" in caplog.text, f"文件改动后应该重新建索引，实际日志：{caplog.text}"
    assert any("/pong" in b for b in bodies), "重建后的索引内容应该反映改动之后的最新代码"
