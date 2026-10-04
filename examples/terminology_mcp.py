"""Offline, read-only MCP example. Run with the project Python interpreter."""
from mcp.server.fastmcp import FastMCP

server = FastMCP("StudyPage terminology")
TERMS = {
    "gradient descent": "梯度下降：沿目标函数负梯度方向迭代更新参数的优化方法。",
    "overfitting": "过拟合：模型过度适应训练样本，导致对新样本泛化较差。",
    "recursion": "递归：通过调用自身处理更小的子问题，并用终止条件结束。",
}

@server.tool()
def lookup_term(term: str) -> str:
    """Look up a term in a small local dictionary; never modifies files."""
    return TERMS.get(term.strip().lower(), "小词典中没有该术语；请根据课程资料核对。")

if __name__ == "__main__":
    server.run(transport="stdio")
