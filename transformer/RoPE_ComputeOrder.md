## RoPE的真实计算顺序：先各自旋转成向量，再做点积

延续[Transformer.md 3.2节"位置编码"](Transformer.md#32-位置编码)的内容。一个容易搞反的地方：**RoPE不是"先算出Q、K两个token之间差了多少角度，再拿这个角度差构造一个向量"，是反过来的——Q和K各自独立按自己的绝对位置旋转成一个具体向量，然后这两个已经旋转好的向量直接做点积。"点积结果只取决于相对角度差"是点积算完之后能证明出来的一个数学性质，不是计算流程里真实存在的一步。**

这个结论分两层证据，分开说清楚可信度。

## 1 数学证明：旋转矩阵的性质

对2D旋转矩阵$R(\theta)$，有两个基本性质：

- **正交性**：$R(\theta)^T = R(-\theta)$（转置等于反向旋转）
- **复合律**：$R(a)R(b) = R(a+b)$（两次旋转叠加=角度相加）

把Q向量在位置$m$旋转$m\theta$、K向量在位置$n$旋转$n\theta$，两者点积：

$$q'^Tk' = (R(m\theta)q)^T(R(n\theta)k) = q^TR(m\theta)^TR(n\theta)k = q^TR(-m\theta)R(n\theta)k = q^TR((n-m)\theta)k$$

推导过程只用到了上面两条性质，每一步都是严格成立的代数变换，不是近似或经验规律。这个恒等式说明：**q'·k'这个数字，必然只取决于(n-m)θ，不取决于m、n各自绝对多大**——这是能被证明的，不是观察到的巧合。

## 2 数值验证：不止一次用真实代码跑出过

在Context Window章节讨论RoPE角度直觉时，用真实numpy代码验证过这个性质（详见[context-window/ContextWindow.md](../context-window/ContextWindow.md)引用的[transformer/draw_rope_angle_intuition.py](draw_rope_angle_intuition.py)脚本）：

- m=3,n=7（相对距离4）和m=103,n=107（相对距离也是4）——两组点积算出来完全相等，精确到小数点后多位
- 跨越"整圈边界"的位置对（比如47116→47118）和普通位置对（5000→5002），点积也完全相等，验证了sin/cos在2π整数倍处的平滑连续性

这些不是理论推导，是拿具体数字跑代码得到的实测结果，跟第1节的证明相互印证。

## 3 真实开源代码：确认工程实现里的计算顺序

第1、2节证明的是"这个数学关系成立"，但没有直接证明"模型代码是不是真的按'先各自旋转、再点积'这个顺序实现的"——这一点需要去看真实代码，不能靠数学证明替代。

查的是HuggingFace `transformers`库（业界最主流的开源Transformer实现之一）里Llama模型的RoPE实现，源码地址：[modeling_llama.py](https://github.com/huggingface/transformers/blob/main/src/transformers/models/llama/modeling_llama.py)。

```python
def rotate_half(x):
    """Rotates half the hidden dims of the input."""
    x1 = x[..., : x.shape[-1] // 2]
    x2 = x[..., x.shape[-1] // 2 :]
    return torch.cat((-x2, x1), dim=-1)

def apply_rotary_pos_emb(q, k, cos, sin, unsqueeze_dim=1):
    cos = cos.unsqueeze(unsqueeze_dim)
    sin = sin.unsqueeze(unsqueeze_dim)
    q_embed = (q * cos) + (rotate_half(q) * sin)
    k_embed = (k * cos) + (rotate_half(k) * sin)
    return q_embed, k_embed
```

调用处（`LlamaAttention.forward()`里）：

```python
query_states, key_states = apply_rotary_pos_emb(query_states, key_states, cos, sin)
attn_weights = torch.matmul(query_states, key_states.transpose(2, 3)) * scaling
```

代码清楚显示了两个独立的步骤，顺序不能颠倒：

1. `apply_rotary_pos_emb`——Q和K**分别**用自己位置对应的`cos`、`sin`张量做旋转（`cos`、`sin`是提前按位置算好的表，第m行对应位置m的cos(mθ)/sin(mθ)），这一步两者互不干扰，各转各的
2. `torch.matmul(query_states, key_states.transpose(2, 3))`——把上一步**已经转好**的Q、K做矩阵乘法（也就是点积），这才是attention分数

全程没有出现"计算(n-m)这个相对距离、再拿它去构造什么东西"这一步——"点积结果只跟相对距离有关"，只是这两步算完之后，数字上恰好满足第1节证明的那个性质，不是代码里专门算出来的一个中间量。

## 结论

三层证据合在一起：**数学上可以严格证明、数值上多次验证过、并且在真实开源代码里能看到对应的实现步骤**——"先各自独立旋转成向量、再做点积"这个计算顺序是有实锤依据的，"点积只取决于相对距离"是这个顺序算出来的必然结果，不是计算流程本身的一步。
