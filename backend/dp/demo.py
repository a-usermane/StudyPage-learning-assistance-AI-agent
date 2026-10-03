"""Replaceable demonstration answer adapter."""
from backend.domain.models import DEMO

DICTIONARY = {
    "gradient descent": ("梯度下降", "一种迭代优化方法：沿目标函数梯度的反方向调整参数，以降低目标函数的值。"),
    "learning rate": ("学习率", "控制每次参数更新的步长。在梯度下降中，学习率乘以梯度得到更新幅度。"),
    "overfitting": ("过拟合", "模型过度适应训练数据的细节或噪声，在未见过的数据上表现变差。"),
    "variable": ("变量", "程序中绑定值的名称。具体定义与作用域必须查看代码，演示词典不会推断定义位置。"),
    "function": ("函数", "接收输入并执行某项操作或返回结果的代码单元，具体行为应以源代码为准。"),
    "matrix": ("矩阵", "按行和列排列的数或表达式，可用来表示数据和线性变换。"),
    "vector": ("向量", "一组有顺序的分量。在课程中可表示方向、坐标或特征，含义取决于上下文。"),
    "algorithm": ("算法", "解决一类问题的明确步骤，例如排序或查找。"),
    "recursion": ("递归", "函数通过调用自身处理规模更小的同类问题，需要终止条件。"),
    "derivative": ("导数", "函数在某一点附近变化率的量度。"),
    "probability": ("概率", "量化事件发生可能性的数值，取值通常在 0 到 1 之间。"),
}

class DemoAnswerProvider:
    def answer(self, action, selected, question, context):
        term = selected.casefold().strip(" .,:;!?\n\t")
        if action in ("translate", "explain"):
            known = DICTIONARY.get(term)
            if known:
                content = f"内置词典示例\n{selected}：{known[0]}"
                if action == "explain":
                    content += f"\n\n{known[1]}\n\n这是通用词典释义，未分析本课程上下文。"
            else:
                content = f"内置词典没有这段内容。演示版无法生成真实翻译或解释。\n\n所选原文：\n{selected}"
        elif action == "summary":
            lines = [line.strip() for line in context.splitlines() if line.strip()]
            content = "当前页原文摘录（不是 AI 总结）\n\n" + ("\n".join(lines[:8])[:1800] if lines else "本页无可提取文字，首版不支持 OCR。")
        else:
            content = f"已记录你的问题：{question}\n\n演示版未生成解答。以下是提问时关联的原文：\n\n"
            content += selected or context[:1400] or "本页无可提取文字，首版不支持 OCR。"
        return DEMO + "\n\n" + content
