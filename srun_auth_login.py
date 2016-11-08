
#!/usr/bin/python
# coding:utf8
# Crate time: 2016.11.08   Version: 1.0
#
# BUG REPORTS
#    Report this scripts bugs to yanshanchen@hotmail.com

import urllib
import os

def check_network():
    check_code_one = os.system('ping -w 1 -n 1 223.5.5.5 > nul')
    check_code_two = os.system('ping -w 1 -n 1 114.114.114.114 > nul')
    if check_code_one == 0 or check_code_two == 0:
        return 0
    return 1

if __name__ == '__main__':

    # 账户名和密码，不要将前后的冒号去掉了.
    username = "201404000000"
    password = "123456"

    # isp_name : 
    #     联通 -> unicom  
    #     移动 -> cmcc 
    #     电信 -> telecom
    isp_name = "unicom"

    isp_name_str = "@" + isp_name
    post_date_dict = {
        "username": username + isp_name_str,
        "password": password,
        "action": "login",
        "ac_id": 1,
        "domain": isp_name_str
    }
    post_date = urllib.urlencode(post_date_dict)
    login_url = "http://172.21.5.253:803/srun_portal_pc.php"

    if check_network():
        urllib.urlopen(login_url, post_date)