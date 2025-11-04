import json
import urllib.request
import urllib.error

class Aria2RPC:
    def __init__(self, url: str, secret: str | None = None, timeout: float = 10.0):
        self.url = url.rstrip("/")
        self.token = f"token:{secret}" if secret else None
        self.timeout = timeout
        self._id = 0

    def _call(self, method: str, params=None):
        self._id += 1
        if params is None:
            params = []
        if self.token is not None:
            params = [self.token] + params
        body = json.dumps({"jsonrpc":"2.0","id":self._id,"method":f"aria2.{method}","params":params}).encode("utf-8")
        req = urllib.request.Request(self.url, data=body, headers={"Content-Type":"application/json"})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except urllib.error.URLError as e:
            raise RuntimeError(f"aria2rpc connection error: {e}") from e
        if "error" in data:
            raise RuntimeError(f"aria2rpc error: {data['error']}")
        return data.get("result")

    # Common methods
    def addUri(self, uris, options=None):
        params = [uris]
        if options: params.append(options)
        return self._call("addUri", params)

    def tellStatus(self, gid, keys=None):
        params = [gid]
        if keys: params.append(keys)
        return self._call("tellStatus", params)

    def tellActive(self, keys=None):
        return self._call("tellActive", [keys] if keys else [])

    def tellWaiting(self, offset, num, keys=None):
        params = [offset, num] + ([keys] if keys else [])
        return self._call("tellWaiting", params)

    def tellStopped(self, offset, num, keys=None):
        params = [offset, num] + ([keys] if keys else [])
        return self._call("tellStopped", params)

    def remove(self, gid): return self._call("remove", [gid])
    def pause(self, gid):  return self._call("pause", [gid])
    def unpause(self, gid):return self._call("unpause", [gid])

    def changeGlobalOption(self, opts: dict):
        return self._call("changeGlobalOption", [opts])
