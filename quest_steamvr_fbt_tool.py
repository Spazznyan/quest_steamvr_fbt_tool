import argparse
import configparser
import json
import logging
import threading
import traceback

from math import asin, atan
from typing import List, Tuple, Optional

import openvr
import wx
import wx.adv

from pythonosc import udp_client

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

formatter = logging.Formatter("%(asctime)s - %(levelname)s:%(name)s - %(message)s")
file_handler = logging.FileHandler("qsft_log.txt", encoding="utf-8")
file_handler.setFormatter(formatter)
stream_handler = logging.StreamHandler()
stream_handler.setFormatter(formatter)
logger.addHandler(file_handler)
logger.addHandler(stream_handler)

thread_terminate = False

def error_handling():
    logger.critical(traceback.format_exc())
    wx.MessageBox("Error occured:\n"+traceback.format_exc(), "Quest SteamVR FBT Tool", wx.ICON_ERROR)
    global thread_terminate
    thread_terminate = True
    wx.Exit()

def get_all_device_serial() -> List[str]:
    ret = []
    i = 0
    while True:
        serial = openvr.IVRSystem().getStringTrackedDeviceProperty(i, openvr.Prop_SerialNumber_String)
        if serial == "":
            return ret
        ret.append(serial)
        i += 1

def get_device_index(device_name: str, ignore: bool) -> int:
    i = 0
    while True:
        serial_num = openvr.IVRSystem().getStringTrackedDeviceProperty(i, openvr.Prop_SerialNumber_String)
        if serial_num == device_name:
            return i
        if serial_num == "":
            if ignore:
                return None
            raise RuntimeError("指定されたデバイスが見つかりませんでした。")
        i += 1

def get_position(matrix: List[List[float]]) -> Tuple[float, float, float]:
    pos_x = matrix[0][3]
    pos_y = matrix[1][3]
    pos_z = matrix[2][3]
    return pos_x, pos_y, pos_z

def get_euler_angle(matrix: List[List[float]]) -> Tuple[float, float, float]:
    rot_y = asin(matrix[0][2])
    if rot_y != 0:
        rot_x = atan(-matrix[1][2]/matrix[2][2])
        rot_z = atan(-matrix[0][1]/matrix[0][0])
    else:
        rot_x = atan(matrix[2][1]/matrix[1][1])
        rot_z = 0
    return rot_x, rot_y, rot_z


def run_tracker_server(addr: str, port: int, use_device: List[str], ignore_not_found_device: bool, standard_device: Optional[str], delta: float):
    try:
        client = udp_client.SimpleUDPClient(addr, port)
        poses = []
        device_indexes = []
        for device in use_device:
            i = get_device_index(device, ignore_not_found_device)
            if i is not None:
                device_indexes.append(i)
        assert 0 < len(device_indexes) < 9
    except Exception:
        error_handling()
        return
    
    if standard_device is not None:
        try:
            i = get_device_index(standard_device, False)
            poses, _ = openvr.VRCompositor().getLastPoses(poses, None)
            pose = poses[i]
            y_delta = -1 * [list(l) for l in list(pose.mDeviceToAbsoluteTracking)][1][3] + delta
        except Exception:
            error_handling()
            return
    else:
        y_delta = 0

    while True:
        if thread_terminate:
            logger.info("Terminate signal received.")
            wx.Exit()
            return
        try:
            poses, _ = openvr.VRCompositor().getLastPoses(poses, None)
            for i,j in enumerate(device_indexes):
                pose = poses[j]
                m = [list(l) for l in list(pose.mDeviceToAbsoluteTracking)]
                pos_x, pos_y, pos_z = get_position(m)
                rot_x, rot_y, rot_z = get_euler_angle(m)
                client.send_message(
                    f"/tracking/trackers/{i+1}/position",
                    [
                        -pos_x, # マイナスにしないと向きが逆になる
                        pos_y + y_delta,
                        pos_z,
                    ]
                )
                client.send_message(
                    f"/tracking/trackers/{i+1}/rotation/x",
                    [
                        rot_x,
                    ]
                )
                client.send_message(
                    f"/tracking/trackers/{i+1}/rotation/y",
                    [
                        rot_y,
                    ]
                )
                client.send_message(
                    f"/tracking/trackers/{i+1}/rotation/z",
                    [

                        rot_z,
                    ]
                )
        except Exception:
            error_handling()
            return

def parse_arg_and_config():
    conf = configparser.ConfigParser()
    conf.read_dict(
        {
            "Connection": {
                "addr": "127.0.0.1",
                "port": "9000"
            },
            "Devices": {
                "use_device": "[]",
                "ignore_not_found_device": "False",
                "delta": "0.05"
            },
            "Log": {
                "level": "info"
            }
        }
    )
    conf.read("./qsft_config.ini", "UTF-8")

    addr = conf["Connection"].get("addr")
    port = conf["Connection"].getint("port")
    use_device = json.loads(conf["Devices"].get("use_device"))
    ignore_not_found_device = conf["Devices"].getboolean("ignore_not_found_device")
    standard_device = conf["Devices"].get("standard_device")
    delta = conf["Devices"].getfloat("delta")
    debug = conf["Log"].getboolean("debug")

    parser = argparse.ArgumentParser()
    parser.add_argument("--addr", default=addr, type=str)
    parser.add_argument("--port", default=port, type=int)
    parser.add_argument("--use_device", default=use_device, action="append", type=str)
    parser.add_argument("--ignore_not_found_device", action="store_true")
    parser.add_argument("--standard_device", default=standard_device, type=str)
    parser.add_argument("--delta", default=delta, type=float)
    parser.add_argument("--debug", action="store_true")

    args = parser.parse_args()

    if args.debug or debug:
        logger.setLevel(logging.DEBUG)

    return (
        args.addr,
        args.port,
        args.use_device,
        args.ignore_not_found_device or ignore_not_found_device,
        args.standard_device,
        args.delta,
    )

class TaskBar(wx.adv.TaskBarIcon):
    def __init__(self):
        wx.adv.TaskBarIcon.__init__(self)
        icon = wx.Icon("qsft.png", wx.BITMAP_TYPE_ANY)
        self.SetIcon(icon, "Quest SteamVR FBT Tool")
        self.Bind(wx.adv.EVT_TASKBAR_LEFT_UP, self.on_leftclick)
    
    def on_leftclick(self, _):
        pass

    def CreatePopupMenu(self):
        menu = wx.Menu()
        menu.Append(1, "Exit")
        self.Bind(wx.EVT_MENU, self.on_click_menu)
        return menu
    
    def on_click_menu(self, event):
        if event.GetId() == 1:
            logger.debug("Exit called.")
            global thread_terminate
            thread_terminate = True
            logger.debug("Joining thread...")
            thread.join()
            logger.debug("Thread terminate completed.")
            self.Destroy()
            wx.Exit()

try:
    openvr.init(openvr.VRApplication_Overlay)
except Exception:
    error_handling()

if __name__ == "__main__":
    logger.info(f"Devices: "+ ", ".join(get_all_device_serial()))

    thread_terminate = False
    try:
        thread = threading.Thread(
            target=run_tracker_server,
            args=parse_arg_and_config(),
        )
    except Exception:
        error_handling()

    thread.start()
    app = wx.App()
    TaskBar()
    app.MainLoop() 

