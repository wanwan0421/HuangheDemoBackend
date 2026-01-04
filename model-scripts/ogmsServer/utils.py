import http.client as httplib
import json
import requests
import hashlib
import os
import random
import base64
from codecs import encode, decode

charstr = "QWERTYUIOPASDFGHJKLZXCVBNMzyxwvutsrqponmlkjihgfedcba!@#$%^&*()"


class HttpHelper:
    @staticmethod
    def Request_get_url_sync(url: str) -> json:
        try:
            res = requests.get(url)
            if res.status_code == 200:
                return res.content, res.headers.get("Content-Disposition")
        except Exception as e:
            return "Error"

    @staticmethod
    def Request_get_sync(ip: str, port: int, path: str, headers: object = {}) -> json:
        try:
            conn = httplib.HTTPConnection(ip, port)
            conn.request("GET", path, headers=headers)
            res = conn.getresponse()
            jsData = json.loads(res.read())
            return jsData
        except Exception as e:
            return f"Error:{e}"

    @staticmethod
    def Request_get_stream_sync(ip: str, port: int, path: str) -> str:
        try:
            conn = httplib.HTTPConnection(ip, port)
            conn.request("GET", path)
            res = conn.getresponse()
            jsData = res.read().decode("utf-8").encode("mbcs")
            return jsData
        except Exception as e:
            return "Error"

    @staticmethod
    def Request_get_str_sync(ip: str, port: int, path: str, headers: object = None):
        try:
            conn = httplib.HTTPConnection(ip, port)
            conn.request("GET", path, headers=headers)
            res = conn.getresponse()
            jsData = res.read().decode("utf-8")
            return jsData
        except Exception as e:
            return "Error"

    @staticmethod
    def Request_post_json_sync(
        ip: str, port: int, path: str, params: object = None, headers: object = None
    ):
        # 构建完整的URL
        url = f"http://{ip}:{port}{path}"
        try:
            response = requests.post(url, json=params, headers=headers)
            response.raise_for_status()  # 如果响应状态码不是200，会抛出异常
            return response.json()  # 返回JSON格式的响应数据
        except requests.exceptions.HTTPError as http_err:
            print(f"HTTP error occurred: {http_err}")
            return None
        except Exception as err:
            print(f"Other error occurred: {err}")
            return None

    @staticmethod
    def Request_post_sync(
        ip: str, port: int, path: str, params: object = None, files: object = None
    ):
        try:
            r = requests.post(
                "http://" + ip + ":" + str(port) + path, params, files=files
            )
            jsData = json.loads(r.text)
            return jsData
        except Exception as e:
            return "Error"

    @staticmethod
    def Request_put_sync(ip: str, port: int, path: str):
        conn = httplib.HTTPConnection(ip, port)
        conn.request("PUT", path)
        res = conn.getresponse()
        jsData = json.loads(res.read())
        return jsData


class CommonMethod:
    @staticmethod
    def IsGUID(statevalue: str):
        if isinstance(statevalue, str):
            if len(statevalue) == 36:
                strs = statevalue.split("-")
                for index, item in enumerate(strs):
                    if len(item) == 0:
                        return False
                return True
            else:
                return False
        else:
            return False

    @staticmethod
    def getJsonValue(jsobject, key):
        if jsobject == "" or isinstance(jsobject, str):
            return ""
        if key in jsobject:
            return jsobject[key]
        else:
            return ""

    @staticmethod
    def getJsonValues(jsobject, keys):
        if jsobject == "" or isinstance(jsobject, str):
            return ""
        for key in keys:
            if key in jsobject:
                return jsobject[key]
        return ""

    @staticmethod
    def getFileMd5(filename: str) -> str:
        if not os.path.isfile(filename):
            return
        myhash = hashlib.md5()
        f = open(filename, "rb")
        while True:
            b = f.read(8096)
            if not b:
                break
            myhash.update(b)
        f.close()
        return myhash.hexdigest()

    @staticmethod
    def encryption(buffer: str) -> str:
        a = encode(buffer.encode(), "hex")
        a = str((base64.encodebytes(a)), "utf-8")[0:-1]
        a = "".join(random.sample(charstr, 5)) + a + "".join(random.sample(charstr, 5))
        a = str(base64.encodebytes(a.encode()), "utf-8")[0:-1]
        return a

    @staticmethod
    def decryption(buffer: str) -> str:
        b = str(base64.decodebytes(buffer.encode("utf-8")), "utf-8")
        b = b[5:]
        b = b[0:-5]
        b = base64.decodebytes(b.encode())
        b = str(decode(b, "hex"), "utf-8")
        return b
