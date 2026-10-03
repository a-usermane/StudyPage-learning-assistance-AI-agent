"""代码阅读样例：文件只会显示，不会执行。"""

def gradient_descent(weight, gradient, learning_rate):
    """Return one parameter update."""
    return weight - learning_rate * gradient


learning_rate = 0.05
weight = 2.0
gradient = 0.8
updated_weight = gradient_descent(weight, gradient, learning_rate)

# 划词选择 variable 或 function，可以查看内置词典示例。
# 选中 updated_weight 提问，演示版只会关联原文，不推断定义。
