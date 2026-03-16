from typing import Any, Dict, List, Optional
from mcp.server.fastmcp import FastMCP
import os
import requests
import json

# 常量定义
BASE_URL = "http://172.21.252.222:8080"
AUTH_TOKEN = "883ada2fc996ab9487bed7a3ba21d2f1"
HEADERS = {"token": AUTH_TOKEN}

# Initialize FastMCP server
mcp = FastMCP("geoDataProcessor")


@mcp.tool()
async def list_all_tools() -> str:
    """
    查询工具库中所有工具的缩略信息，一次性返回所有工具

    Returns:
        str: 包含工具ID、名称和描述的JSON字符串
    """
    try:
        # 设置适当的limit值，分批获取所有工具
        limit = 100  # 每次请求100个方法，减轻服务端压力
        page = 1
        all_tools = []
        total_count = 0

        # 第一次请求，获取总数
        url = f"{BASE_URL}/container/method/listWithTag?page={page}&limit={limit}"
        response = requests.get(url, headers=HEADERS)

        if response.status_code != 200:
            return f"请求失败，状态码: {response.status_code}"

        data = response.json()
        if data["code"] != 0:
            return f"请求失败，错误信息: {data['msg']}"

        total_count = data["page"]["totalCount"]
        total_pages = (total_count + limit - 1) // limit  # 计算总页数

        # 提取第一页的工具信息
        for tool in data["page"]["list"]:
            all_tools.append({
                "id": tool["id"],
                "name": tool["name"]
            })

        # 如果有多页，继续请求后续页面
        for page in range(2, total_pages + 1):
            url = f"{BASE_URL}/container/method/listWithTag?page={page}&limit={limit}"
            response = requests.get(url, headers=HEADERS)

            if response.status_code == 200:
                data = response.json()
                if data["code"] == 0:
                    for tool in data["page"]["list"]:
                        all_tools.append({
                            "id": tool["id"],
                            "name": tool["name"]
                        })

        result = {
            "total_count": total_count,
            "tools": all_tools
        }

        return json.dumps(result, ensure_ascii=False, indent=2)

    except Exception as e:
        return f"查询工具列表失败: {str(e)}"


@mcp.tool()
async def search_tools_by_keyword(keyword: str) -> str:
    """
    根据关键词获取工具，一次性返回所有符合条件的工具，关键词需要是英文的

    Args:
        keyword: 搜索关键词

    Returns:
        str: 包含工具详细信息的JSON字符串
    """
    try:
        # 设置较大的limit值，一次性获取所有符合条件的工具
        limit = 500  # API文档提到每次最多请求500个方法
        page = 1
        all_tools = []
        total_count = 0

        # 第一次请求，获取总数
        url = f"{BASE_URL}/container/method/listWithTag?page={page}&limit={limit}&key={keyword}"
        response = requests.get(url, headers=HEADERS)

        if response.status_code != 200:
            return f"请求失败，状态码: {response.status_code}"

        data = response.json()
        if data["code"] != 0:
            return f"请求失败，错误信息: {data['msg']}"

        total_count = data["page"]["totalCount"]
        total_pages = (total_count + limit - 1) // limit  # 计算总页数

        # 提取第一页的工具信息
        for tool in data["page"]["list"]:
            all_tools.append({
                "id": tool["id"],
                "name": tool["name"],
                "description": tool["description"],
                "longDesc": tool["longDesc"],
                "params": tool["params"]
            })

        # 如果有多页，继续请求后续页面
        for page in range(2, total_pages + 1):
            url = f"{BASE_URL}/container/method/listWithTag?page={page}&limit={limit}&key={keyword}"
            response = requests.get(url, headers=HEADERS)

            if response.status_code == 200:
                data = response.json()
                if data["code"] == 0:
                    for tool in data["page"]["list"]:
                        all_tools.append({
                            "id": tool["id"],
                            "name": tool["name"],
                            "description": tool["description"],
                            "longDesc": tool["longDesc"],
                            "params": tool["params"]
                        })

        result = {
            "total_count": total_count,
            "tools": all_tools
        }

        return json.dumps(result, ensure_ascii=False, indent=2)

    except Exception as e:
        return f"搜索工具失败: {str(e)}"


@mcp.tool()
async def get_tool_details(name: str) -> str:
    """
    查询某个方法名称的详细信息

    Args:
        name: 方法名称

    Returns:
        str: 包含工具详细信息的JSON字符串
    """
    try:
        url = f"{BASE_URL}/container/method/infoByName/{name}"
        response = requests.get(url, headers=HEADERS)

        if response.status_code != 200:
            return f"请求失败，状态码: {response.status_code}"

        data = response.json()
        if data["code"] != 0:
            return f"请求失败，错误信息: {data['msg']}"

        # 提取详细信息
        tool = data["method"]
        result = {
            "id": tool["id"],
            "name": tool["name"],
            "description": tool["description"],
            "longDesc": tool["longDesc"],
            "params": tool["params"],
            "paramType": data["paramType"]
        }

        return json.dumps(result, ensure_ascii=False, indent=2)

    except Exception as e:
        return f"获取工具详情失败: {str(e)}"


@mcp.tool()
async def invoke_tool(tool_id: int, params: Dict[str, Any]) -> str:
    """
    调用地理数据处理方法

    Args:
        tool_id: 工具ID，可以通过list_all_tools或search_tools_by_keyword或get_tool_details获取
        params: 工具参数，格式为 {"val0": value0, "val1": value1, ...}
               注意：参数的键名不是参数的实际名称，而是按照参数在工具定义中的顺序编号：
               - val0: 第一个参数
               - val1: 第二个参数
               - val2: 第三个参数，以此类推

               对于文件输入类型的参数，需要先使用upload_file工具上传文件，然后将返回的文件ID作为参数值。注意，只需要传入id，并不需要完整的url。
               - 如果参数类型是单个文件，则传入文件ID字符串
               - 如果参数类型是文件列表，则传入文件ID列表

               对于文件输出类型的参数，只需传入输出文件名

               对于布尔类型参数，可以传入布尔值(true/false)或字符串("true"/"false")
               对于数值类型参数，可以传入数值或字符串形式的数值

    Returns:
        str: 调用结果的JSON字符串，包含输出文件信息和执行日志
    """
    try:
        # 构建请求URL
        url = f"{BASE_URL}/container/method/invoke/{tool_id}"

        # 发送POST请求
        response = requests.post(url, headers=HEADERS, json=params)

        if response.status_code != 200:
            return f"请求失败，状态码: {response.status_code}"

        data = response.json()
        if data["code"] != 0:
            return f"请求失败，错误信息: {data['msg']}"

        # 处理响应结果
        result = {
            "code": data["code"],
            "msg": data["msg"],
            "output": data.get("output", {}),  # 输出文件信息
            "info": data.get("info", "")       # 执行日志
        }

        return json.dumps(result, ensure_ascii=False, indent=2)

    except Exception as e:
        return f"调用工具失败: {str(e)}"


@mcp.tool()
async def upload_file(file_path: str) -> str:
    """
    将文件上传文件到数据中转服务区, 并返回文件ID
    如果是矢量文件的话，需要为每个矢量数据各创建一个压缩包，把这个矢量数据的关联文件放到这个压缩包中，然后上传这个压缩包。
    是一个矢量数据一个压缩包。不是所有的矢量数据都放在一个压缩包中。
    Args:
        file_path: 文件路径
    Returns:
        str: 上传成功后的文件URL，只需要返回文件ID
    """
    try:
        # 读取文件内容
        with open(file_path, 'rb') as f:
            file_content = f.read()

        # 构建请求数据
        files = {
            'datafile': (os.path.basename(file_path), file_content)
        }
        data = {
            'name': os.path.basename(file_path)
        }

        # 发送POST请求
        response = requests.post('http://221.224.35.86:38083/data',
                                 files=files,
                                 data=data)

        if response.status_code == 200:
            result = response.json()
            download_url = 'http://221.224.35.86:38083/data/' + \
                result['data']['id']
            return download_url
        else:
            raise Exception('服务端错误')

    except Exception as e:
        raise Exception(f'文件上传失败: {str(e)}')

if __name__ == "__main__":
    # Initialize and run the server
    print("Starting geoDataProcessor server...")
    mcp.run(transport='stdio')
