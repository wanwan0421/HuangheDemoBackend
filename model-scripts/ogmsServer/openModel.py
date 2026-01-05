# Date : 2024-8-8
# Author : Fengyuan(Franklin) Zhang
# Email : franklinzhang@foxmail.com
# Description : Usage ogms task
from six import print_

from .base import Service

from .utils import HttpHelper
from .responseHandler import ResultUtils

import json
import time
import sys
import os
import configparser
import urllib.parse
import secrets

# TODO:
# 文件识别
# 路径校验
# 下载完善


class OGMSTask(Service):
    def __init__(self):
        super().__init__("172.21.252.204", 8061)
        self.origin_lists = {}
        self.subscirbe_lists = {}
        self.tid: str = None
        self.status: int = None
        self.inputs = []
        self.outputs = []
        self.dataInfo = []
        self.modelInfo = []
        # 创建一个配置解析器对象
        config = configparser.ConfigParser()
        # 读取配置文件
        config_path = "./config.ini"
        if not os.path.exists(config_path):
            print("计算容器配置出错，请联系管理员！")
            sys.exit(1)
        config.read(config_path)
        self.username = config.get("DEFAULT", "username").strip()
        self.portalServer = config.get("DEFAULT", "portalServer").strip()
        self.portalPort = config.get("DEFAULT", "portalPort").strip()
        self.managerServer = config.get("DEFAULT", "managerServer").strip()
        self.managerPort = config.get("DEFAULT", "managerPort").strip()
        self.dataServer = config.get("DEFAULT", "dataServer").strip()
        self.dataPort = config.get("DEFAULT", "dataPort").strip()
        if not (
                self.username
                or self.portalServer
                or self.portalPort
                or self.managerServer
                or self.managerPort
                or self.dataServer
                or self.dataPort
        ):
            print("计算容器配置出错，请联系管理员！")
            sys.exit(1)

    def to_dict(self) -> dict:
        return {
            "ip": self.ip,
            "port": self.port,
            "tid": self.tid,
            "pid": self.pid,
            "status": self.status,
            "inputs": self.inputs,
            "outputs": self.outputs,
        }

    # 暂时废弃
    def resolvingMDL_discarded(self, pid: str) -> ResultUtils:
        result = HttpHelper.Request_get_sync(
            "172.21.213.151", 8066, "/computableModel/ModelInfo_pid/" + pid
        )
        if result["code"] == 0:
            self.origin_lists = self.parse_model_data(result["data"])
            return ResultUtils.success()
        else:
            return ResultUtils.error(msg="No document found with the provided pid.")

    def resolvingMDL(self, mdlData: str) -> ResultUtils:
        if mdlData:
            self.origin_lists = self.parse_model_data(mdlData)
            return ResultUtils.success()
        else:
            # TODO: 处理无mdl的情况
            return ResultUtils.error(msg="解析mdl失败，请联系管理员！")

    def parse_model_data(self, mdl_data: dict) -> dict:
        def extract_children(udx_node):
            return [
                {
                    "eventId": child["name"],
                    "eventName": child["name"],
                    "eventDesc": child["name"],
                    "eventType": child["type"]
                    .replace("DTKT_", "")
                    .replace("REAL", "FLOAT"),
                    "child": "true",
                    "value": "",
                }
                for child in udx_node.get("UdxNode", [])
            ]

        def process_event(event, evt, dataset_item, data, is_input=True):
            entry_type = "inputs" if is_input else "outputs"
            entry = {
                "statename": event.get("name"),
                "event": evt.get("name"),
                "optional": evt.get("optional"),
            }
            if is_input:
                entry.update(
                    {
                        "url": "",
                        "tag": dataset_item.get("name"),
                        "suffix": "",
                    }
                )
            else:
                entry["template"] = {
                    "type": "id" if "externalId" in dataset_item else "None",
                    "value": dataset_item.get("externalId", ""),
                }

            if dataset_item["type"] == "internal" and dataset_item.get(
                    "UdxDeclaration"
            ):
                udx_node = dataset_item["UdxDeclaration"][0].get("UdxNode")
                if udx_node:
                    entry["children"] = extract_children(
                        dataset_item["UdxDeclaration"][0]["UdxNode"][0]
                    )

            data[entry_type].append(entry)

        data = {
            "outputs": [],
            "port": self.port,  # Fill with actual port if available
            "inputs": [],
            "ip": self.ip,  # Fill with actual IP if available
            "pid": mdl_data.get("md5", ""),
            "oid": mdl_data.get("id", ""),
            "username": "",  # Fill with actual username if available
        }
        related_datasets = mdl_data["mdlJson"]["ModelClass"][0]["Behavior"][0][
            "RelatedDatasets"
        ][0]["DatasetItem"]

        for model_class in mdl_data.get("mdlJson", {}).get("ModelClass", []):
            for behavior in model_class.get("Behavior", []):
                for state_group in behavior.get("StateGroup", []):
                    for state in state_group.get("States", []):
                        for event in state.get("State", []):
                            for evt in event.get("Event", []):
                                dataset_reference = evt.get(
                                    "ResponseParameter",
                                    evt.get("DispatchParameter", []),
                                )
                                for param in dataset_reference:
                                    dataset_item = next(
                                        (
                                            item
                                            for item in related_datasets
                                            if item["name"] == param["datasetReference"]
                                        ),
                                        None,
                                    )
                                    if dataset_item:
                                        process_event(
                                            event,
                                            evt,
                                            dataset_item,
                                            data,
                                            is_input=(evt.get("type") == "response"),
                                        )

        return data

    def mergeData(self, params: dict) -> ResultUtils:
        def extract_file_suffix(filename: str) -> str:
            """提取文件名的后缀名."""
            return filename.split(".")[-1] if "." in filename else ""

        def update_input_item(input_item: dict, event_data: dict):
            """
            根据 input_data 中的 event_data 更新 origin_data 中的 input_item。
            这个版本增加了对 'value' 字段的特殊处理。
            """
            if "value" in event_data:
                # 如果 event_data 中有 value 字段，直接使用它
                if "children" in input_item and input_item["children"]:
                    child = input_item["children"][0]
                    # 将 value 赋值给正确的子参数
                    child["value"] = event_data["value"]

                # 确保 url 和 name 字段也被正确设置
                if "url" in event_data:
                    input_item["url"] = event_data["url"]
                if "name" in event_data:
                    input_item["suffix"] = extract_file_suffix(event_data["name"])
                return

            # 原有的处理逻辑
            if "children" in event_data:
                input_item["suffix"] = "xml"
                for child in input_item.get("children", []):
                    event_name = child["eventName"]
                    for b_child in event_data["children"]:
                        if event_name in b_child:
                            child["value"] = b_child[event_name]
            else:
                if "name" in event_data:
                    input_item["suffix"] = extract_file_suffix(event_data["name"])

            if "url" in event_data:
                input_item["url"] = event_data["url"]

        def fill_data_with_input(input_data: dict, origin_data: dict) -> dict:
            """根据 input_data 填补 origin_data."""
            for input_item in origin_data.get("inputs", []):
                state_name = input_item.get("statename")
                event_name = input_item.get("event")

                if not state_name or not event_name:
                    return ResultUtils.error(
                        msg=f"Invalid input_item structure: {input_item}"
                    )

                state_data = input_data["inputs"].get(state_name)
                if state_data and event_name in state_data:
                    update_input_item(input_item, state_data[event_name])
            origin_data["username"] = input_data.get("username")
            return origin_data

        filled_origin_data = fill_data_with_input(params, self.origin_lists)
        return self.validData(filled_origin_data)

    def validData(self, merge_data: dict) -> ResultUtils:
        def validate_event(event):

            errors = []
            event_name = f"{event.get('statename')}-{event.get('event')}"

            if event.get("optional") == "False":
                # 必填项
                if not event.get("url"):
                    errors.append(f"{event_name}的中转数据信息有误！")
                if not event.get("suffix"):
                    errors.append(f"{event_name}的文件有误！")
                if "children" in event:
                    for child in event["children"]:
                        if not child.get("value"):
                            errors.append(f"{event_name}子参数有误")
            elif event.get("optional") == "True":
                # 选填项
                if event.get("url") or event.get("suffix") or "children" in event:
                    if not (event.get("url") and event.get("suffix")):
                        errors.append(f"{event_name}子参数有误！")
                    if "children" in event:
                        for child in event["children"]:
                            if not child.get("value"):
                                errors.append(f"{event_name}子参数不能为空！")

            return errors

        def process_inputs(inputs):
            errors = []
            valid_inputs = []
            for event in inputs:
                event_errors = validate_event(event)
                if event_errors:
                    errors.extend(event_errors)
                else:
                    if event.get("optional") == "True":
                        if not (
                                event.get("url")
                                or event.get("suffix")
                                or "children" in event
                        ):
                            # 如果选填项没有值，则跳过
                            continue
                    valid_inputs.append(event)
            return valid_inputs, errors

        def check_username(username):
            errors = []
            if not username:
                errors.append("无用户信息")
            return errors

        # 校验 username
        errors = check_username(merge_data.get("username"))

        # 处理 inputs
        valid_inputs, input_errors = process_inputs(merge_data.get("inputs", []))
        errors.extend(input_errors)

        # 更新数据
        merge_data["inputs"] = valid_inputs

        # 打印错误信息
        if errors:
            return ResultUtils.error(msg="参数有误", data=errors)
        else:
            self.subscirbe_lists = merge_data
            return ResultUtils.success()

    def configInputData(self, params: dict) -> ResultUtils:
        if not params:
            print("参数有误,请检查后重试！")
            sys.exit(0)
        lists = {"inputs": self.uploadData(params), "username": self.username}
        return self.mergeData(lists)

    def _bind(self, data: dict) -> int:
        self.ip = data["ip"]
        self.port = data["port"]
        self.tid = data["tid"]
        return 1

    def refresh(self) -> int:
        data = {"port": self.port, "ip": self.ip, "tid": self.tid}
        res = HttpHelper.Request_post_json_sync(
            self.managerServer,
            self.managerPort,
            "/GeoModeling/computableModel/refreshTaskRecord",
            data,
        )
        if res["code"] == 1:
            status = res["data"]["status"]
            if self.status is None and status == 0:
                print("模型服务正在初始化，请稍后...")
            if self.status == 0 and status == 1:
                print("模型运算中，请稍后...")
            if status == 2:
                hasValue = False
                for output in res["data"]["outputs"]:
                    if output.get("url") is not None and output.get("url") != "":
                        url = output.get("url")
                        print(url)
                        # url = output.get("url")
                        # updated_url = url.replace(
                        #     "http://112.4.132.6:8083",
                        #     "http://geomodeling.njnu.edu.cn/dataTransferServer",
                        # )
                        # output["url"] = updated_url
                        hasValue = True
                if hasValue is False:
                    return -1
                for output in res["data"]["outputs"]:
                    if "[" in output.get("url"):
                        output["multiple"] = True
                self.pid = res["data"]["pid"]
                self.outputs = res["data"]["outputs"]
                print("模型运算完成，获取结果中，请稍后...")
            if status == -1:
                print("模型服务计算异常!")
                sys.exit(1)
            self.status = status
            return status
        else:
            print("模型服务计算异常!")
            sys.exit(1)

    def wait4Status(self, timeout: int = 7200) -> ResultUtils:
        currtime = time.time()
        endtime = currtime + timeout
        self.refresh()
        status = self.status
        while status != 2 and currtime < endtime:
            time.sleep(2)
            self.refresh()
            status = self.status
            currtime = time.time()
        if currtime >= endtime:
            # TODO more judgement
            return ResultUtils.error(msg="任务超时")
        return ResultUtils.success(data=json.dumps(self.to_dict()))

    def uploadData(self, pathList: dict) -> dict:
        inputs = {}
        for category, files in pathList.items():
            inputs[category] = {}
            for key, file_path in files.items():
                file_name = file_path.split("/")[-1]
                inputs[category][key] = {
                    "name": file_name,
                    "url": self.getUploadData(file_path),
                }
        return inputs

    def getUploadData(self, path: str) -> str:
        res = HttpHelper.Request_post_sync(
            self.dataServer,
            self.dataPort,
            "/data",
            files={"datafile": open(path, "rb")},
        )
        if res["code"] == 1:
            url = (
                    "http://geomodeling.njnu.edu.cn/dataTransferServer/data/"
                    + res["data"]["id"]
            )
            return url
        else:
            print("数据上传失败！请稍后重试！")
            sys.exit(0)

    def normalizeInputData(self, params: dict) -> dict:
        """
        支持三种输入：
        - { value: xxx }
        - { path: /local/file }
        - { url: http://xxx }
        统一转换成 mergeData 可识别的结构
        """
        normalized_params = {}

        for state, events in params.items():
            normalized_params[state] = {}
            for event, event_data in events.items():
                if "value" in event_data:
                    # 直接使用 value
                    normalized_params[state][event] = {
                        "value": event_data["value"]
                    }
                elif "path" in event_data:
                    # 上传本地文件并获取 URL
                    file_path = event_data["path"]
                    file_name = os.path.basename(file_path)
                    file_url = self.getUploadData(file_path)
                    normalized_params[state][event] = {
                        "name": file_name,
                        "url": file_url,
                    }
                elif "url" in event_data:
                    # 直接使用提供的 URL
                    normalized_params[state][event] = {
                        "name": event_data.get("name", ""),
                        "url": event_data["url"],
                    }
                else:
                    print(
                        f"Invalid input format for state '{state}', event '{event}'."
                    )
                    sys.exit(1)
        return normalized_params

    # ! download result by state and event
    def downloadResultByStateEvent(self, state: str, event: str, path: str) -> bool:
        pass

    # ! download all results
    def downloadAllData(self) -> bool:
        downloadFilesNum = 0
        downlaodedFilesNum = 0
        if not self.outputs:
            print("没有可下载的数据")
            return False
        for output in self.outputs:
            statename = output["statename"]
            event = output["event"]
            url = output["url"]
            suffix = output["suffix"]

            # 构建文件名
            base_filename = f"{statename}-{event}"
            filename = f"{base_filename}.{suffix}"
            counter = 1

            # 检查文件是否存在
            while os.path.exists(filename):
                filename = f"{base_filename}_{counter}.{suffix}"
                counter += 1

            downloadFilesNum = downloadFilesNum + 1
            # 下载文件并保存
            content = HttpHelper.Request_get_url_sync(url)
            if content:
                with open("./data/" + filename, "wb") as f:
                    f.write(content)
                print(f"Downloaded {filename}")
                downlaodedFilesNum = downlaodedFilesNum + 1
            else:
                print(f"Failed to download {url}")
        if downlaodedFilesNum == 0:
            print("Failed to download files")
            return False
        if downloadFilesNum == downlaodedFilesNum:
            print("All files downloaded successfully")
            return True
        else:
            print("Failed to download some files")
            return True

    def wait4Finish(self, timeout: int = 7200) -> ResultUtils:
        return self.wait4Status(timeout)

    # ! check if this task can be invoked
    def check(self) -> int:
        pass


class OGMSTaskAccess(Service):
    def __init__(self, modelName: str):
        super().__init__("0", 0)
        self.outputs = []
        self.modelName = modelName
        # 创建一个配置解析器对象
        config = configparser.ConfigParser()
        # 读取配置文件
        config_path = "./config.ini"
        if not os.path.exists(config_path):
            print("读取配置信息出错，请联系管理员！")
            sys.exit(1)
        config.read(config_path)
        self.portalServer = config.get("DEFAULT", "portalServer").strip()
        self.portalPort = int(config.get("DEFAULT", "portalPort").strip())
        self.managerServer = config.get("DEFAULT", "managerServer").strip()
        self.managerPort = config.get("DEFAULT", "managerPort").strip()
        if not (
                self.portalServer
                or self.portalPort
                or self.managerServer
                or self.managerPort
        ):
            print("读取配置信息出错，请联系管理员！")
            sys.exit(1)
        self.mdlData: dict
        self.checkModel(modelName=modelName)

    def checkModel(self, modelName: str):
        if not modelName:
            print("请输入模型名称！")
            sys.exit(1)
        encode_url = urllib.parse.quote(modelName)
        # get model pid
        res = HttpHelper.Request_get_sync(
            self.portalServer,
            self.portalPort,
            "/computableModel/ModelInfo_name/" + encode_url,
            )
        if res is None:
            print(f"《{modelName}》模型库维护中，请联系管理员！")
            sys.exit(1)
        else:
            if (
                    res["code"] == 0
                    and res["data"] != None
                    and res["data"].get("md5") != None
            ):
                print("模型资源已载入，准备创建服务！")
                # get first model pid
                pid = res["data"]["md5"]
                self.checkModelService(pid)
                self.mdlData = res["data"]
            else:
                print(f"《{modelName}》资源不存在！")
                sys.exit(1)

    def checkModelService(self, pid: str):
        if not pid:
            print("模型服务启动失败，请联系管理员！")
            sys.exit(1)
        # check if the pid is valid
        resJson = HttpHelper.Request_get_sync(
            self.managerServer, self.managerPort, "/GeoModeling/task/verify/" + pid
        )
        if resJson["code"] == 1:
            if resJson["data"] == True:
                print("模型服务创建成功！")
                return 1
            else:
                print("模型服务创建失败，请联系管理员！")
                sys.exit(1)
        else:
            print("模型服务创建失败，请联系管理员！")
            sys.exit(1)

    def subscribeTask(self, task: OGMSTask) -> ResultUtils:
        res = HttpHelper.Request_post_json_sync(
            self.managerServer,
            self.managerPort,
            "/GeoModeling/computableModel/invoke",
            task.subscirbe_lists,
        )
        print("res:", res)
        if res is None:
            print("模型运行失败，请重试！")
            sys.exit(1)
        else:
            if res["code"] == 1:
                task._bind(res["data"])
                return ResultUtils.success()
            print("模型运行失败，请重试！")
            sys.exit(1)

    def downloadAllData(self) -> bool:
        s_id = secrets.token_hex(8)
        downloadFilesNum = 0
        downlaodedFilesNum = 0
        if not self.outputs:
            print("没有可下载的数据")
            return False

        for output in self.outputs:
            statename = output["statename"]
            event = output["event"]
            url = output["url"]
            suffix = output["suffix"]
            # 构建文件名
            base_filename = f"{statename}-{event}"
            filename = f"{base_filename}.{suffix}"
            counter = 1

            file_path = "./data/" + self.modelName + "_" + s_id + "/" + filename

            dir_path = os.path.dirname(file_path)
            if not os.path.exists(dir_path):
                os.makedirs(dir_path)

            # 检查文件是否存在
            while os.path.exists(file_path):
                filename = f"{base_filename}_{counter}.{suffix}"
                file_path = "./data/" + self.modelName + "_" + s_id + "/" + filename
                counter += 1
            downloadFilesNum = downloadFilesNum + 1
            # 下载文件并保存
            content, cDisposition = HttpHelper.Request_get_url_sync(url)
            if content:
                with open(file_path, "wb") as f:
                    f.write(content)
                print(f"Downloaded {filename}")
                downlaodedFilesNum = downlaodedFilesNum + 1
            else:
                print(f"Failed to download {url}")
        if downlaodedFilesNum == 0:
            print("Failed to download files")
            return False
        if downloadFilesNum == downlaodedFilesNum:
            print("All files downloaded successfully")
            return True
        else:
            print("Failed to download some files")
            return True
        # downloadFilesNum = 0
        # downlaodedFilesNum = 0
        # if not self.outputs:
        #     print("没有可下载的数据")
        #     return False

        # for output in self.outputs:
        #     statename = output["statename"]
        #     event = output["event"]
        #     url = output["url"]
        #     suffix = output["suffix"]
        #     # 构建文件名
        #     base_filename = f"{statename}-{event}"
        #     filename = f"{base_filename}.{suffix}"
        #     counter = 1
        #     s_id = secrets.token_hex(8)
        #     file_path = "./data/" + self.modelName + "_" + s_id + "/" + filename

        #     dir_path = os.path.dirname(file_path)
        #     if not os.path.exists(dir_path):
        #         os.makedirs(dir_path)

        #     # 检查文件是否存在
        #     while os.path.exists(file_path):
        #         filename = f"{base_filename}_{counter}.{suffix}"
        #         file_path = "./data/" + self.modelName + "_" + s_id + "/" + filename
        #         counter += 1
        #     downloadFilesNum = downloadFilesNum + 1
        #     # 下载文件并保存
        #     content, cDisposition = HttpHelper.Request_get_url_sync(url)
        #     if content:
        #         with open("./data/" + filename, "wb") as f:
        #             f.write(content)
        #         print(f"Downloaded {filename}")
        #         downlaodedFilesNum = downlaodedFilesNum + 1
        #     else:
        #         print(f"Failed to download {url}")
        # if downlaodedFilesNum == 0:
        #     print("Failed to download files")
        #     return False
        # if downloadFilesNum == downlaodedFilesNum:
        #     print("All files downloaded successfully")
        #     return True
        # else:
        #     print("Failed to download some files")
        #     return True

    def createTask(self, params: dict) -> ResultUtils:
        # create task
        task = OGMSTask()
        # resolving MDL
        r = task.resolvingMDL(self.mdlData)
        if r.code != 1:
            return r
        # configuration parameter
        c = task.configInputData(params)
        if c.code != 1:
            return c
        self.subscribeTask(task)
        result = task.wait4Finish()
        self.outputs = json.loads(result.data)["outputs"]
        print(self.outputs)
        return ResultUtils.success(data=self.outputs)

    def createTaskWithURL(self, params_with_url: dict) -> ResultUtils:
        # create task
        task = OGMSTask()

        # resolving MDL
        r = task.resolvingMDL(self.mdlData)
        if r.code != 1:
            return r

        # 直接构造符合 mergeData 期望的输入格式
        # 这一步跳过了configInputData和uploadData
        lists_for_merge = {"inputs": params_with_url, "username": task.username}
        c = task.mergeData(lists_for_merge)
        if c.code != 1:
            print(f"数据校验失败，错误码：{c.code}")
            print(f"详细错误信息：{c.data}")
            return c
        self.subscribeTask(task)
        result = task.wait4Finish()
        self.outputs = json.loads(result.data)["outputs"]
        return ResultUtils.success(data=self.outputs)
    
    def createTaskAuto(self, params: dict) -> ResultUtils:
        # create task
        task = OGMSTask()

        # resolving MDL
        r = task.resolvingMDL(self.mdlData)
        if r.code != 1:
            return r
        
        normalized_params = task.normalizeInputData(params)

        lists = {
            "inputs": normalized_params,
            "username": task.username,
        }

        # 直接构造符合 mergeData 期望的输入格式
        c = task.mergeData(lists)
        if c.code != 1:
            return c
        self.subscribeTask(task)
        result = task.wait4Finish()
        self.outputs = json.loads(result.data)["outputs"]
        print(self.outputs)
        return ResultUtils.success(data=self.outputs)

class OGMSDownload:
    def __init__(self, data: list):
        self.outputs = data
        downloadFilesNum = 0
        downlaodedFilesNum = 0
        s_id = secrets.token_hex(8)
        if not self.outputs:
            print("没有可下载的数据")
        for output in self.outputs:
            statename = output["statename"]
            event = output["event"]
            url = output["url"]
            suffix = output["suffix"]

            # 构建文件名
            base_filename = f"{statename}-{event}"
            filename = f"{base_filename}.{suffix}"
            counter = 1

            file_path = "./data/" + self.modelName + "_" + s_id + "/" + filename

            dir_path = os.path.dirname(file_path)
            if not os.path.exists(dir_path):
                os.makedirs(dir_path)

            # 检查文件是否存在
            while os.path.exists(file_path):
                filename = f"{base_filename}_{counter}.{suffix}"
                file_path = "./data/" + self.modelName + "_" + s_id + "/" + filename
                counter += 1
            downloadFilesNum = downloadFilesNum + 1
            # 下载文件并保存
            content = HttpHelper.Request_get_url_sync(url)
            if content:
                with open("./data/" + filename, "wb") as f:
                    f.write(content)
                print(f"Downloaded {filename}")
                downlaodedFilesNum = downlaodedFilesNum + 1
            else:
                print(f"Failed to download {url}")
        if downlaodedFilesNum == 0:
            print("Failed to download files")
            sys.exit(1)
        if downloadFilesNum == downlaodedFilesNum:
            print("All files downloaded successfully")
        else:
            print("Failed to download some files")
