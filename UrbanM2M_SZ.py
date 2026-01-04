import sys
import os
import json

current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

try:
    from ogmsServer import openModel

    lists = {
        "run": {
            "Years_zip": {
                "name": "sz.zip",
                "url": "http://geomodeling.njnu.edu.cn/dataTransferServer/data/da686d2b-d0d6-4a8e-9667-f391be9a550c"
            },
            "st_year": {
                "name": "st_year.xml",
                "url": "http://geomodeling.njnu.edu.cn/dataTransferServer/data/ced8a86f-3c9f-413a-9d3e-1e7e205d97a3"
            },
            "first_sim_year": {
                "name": "first_sim_year.xml",
                "url": "http://geomodeling.njnu.edu.cn/dataTransferServer/data/8003c4cf-1d6a-4e10-b3d2-84eee9238cc2"
            },
            "out_len": {
                "name": "out_len.xml",
                "url": "http://geomodeling.njnu.edu.cn/dataTransferServer/data/4711dc5e-769d-44a8-af30-e4cc973f4caf"
            },
            "land_demands": {
                "name": "land_demands.xml",
                "url": "http://geomodeling.njnu.edu.cn/dataTransferServer/data/d363580b-1417-402e-b3cf-1ec60a4a5bf6",
                "value": "1000"
            },
        }
    }

    taskServer = openModel.OGMSTaskAccess(modelName="UrbanM2M计算模型（用于测试请勿调用）")
    result = taskServer.createTaskWithURL(params_with_url=lists)
    taskServer.downloadAllData()

except ImportError as e:
    print(f"导入模块时出错：{e}")
    print("请确保 'ogmsServer' 文件夹位于正确的路径。")
except Exception as e:
    print(f"在运行模型时发生了一个错误：{e}")