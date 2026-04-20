import os
import sys
import json

# 确保找到ogmsServer
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

def run():
    # 从命令行参数中获取JSON数据文件的路径
    if len(sys.argv) < 2:
        print(json.dumps({"status": "error", "message": "No input file provided"}))
        sys.exit(1)

    input_file = sys.argv[1]

    try:
        with open(input_file, 'r', encoding='utf-8') as f:
            data = json.load(f)

        modelName = data.get('modelName')
        lists = data.get('lists')

        # 导入OGMS
        from ogmsServer import openModel

        # 运行模型
        taskServer = openModel.OGMSTaskAccess(modelName=modelName)
        result = taskServer.createTaskWithURL(params_with_url=lists)
        print("result:", result)

        # createTaskWithURL 失败时通常以 ResultUtils(code != 1) 返回，而不是抛异常。
        result_code = getattr(result, "code", None)
        if result_code is not None and result_code != 1:
            result_msg = str(getattr(result, "msg", "参数有误") or "参数有误")
            result_data = getattr(result, "data", None)
            if isinstance(result_data, list) and result_data:
                detail = " | ".join(str(item) for item in result_data)
                result_msg = f"{result_msg}: {detail}"
            elif result_data:
                result_msg = f"{result_msg}: {result_data}"

            print(json.dumps({"status": "error", "message": result_msg}, ensure_ascii=False))
            sys.exit(1)

        # 下载结果
        # download_result = taskServer.downloadAllData()
        final_output = {
            "status": "success",
            "result": getattr(result, "data", result),
        }
        print(json.dumps(final_output))

    except Exception as e:
        print(json.dumps({"status": "error", "message": str(e)}))
        sys.exit(1)

if __name__ == "__main__":
    run()