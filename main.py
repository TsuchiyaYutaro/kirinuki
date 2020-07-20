# データ取得
import requests
from bs4 import BeautifulSoup

# データ加工
from datetime import datetime, date, timedelta
import pandas as pd
import numpy as np
import json, ast, re, time

# 動画ダウンロード，変数
from pytube import YouTube
from moviepy.editor import *

# その他
import os
import shutil
from tqdm import tqdm

import warnings
warnings.filterwarnings('ignore')


# == 変数 ===================================================================================

# 対象の配信 ID
vid = ''
target_url = f'https://www.youtube.com/watch?v={vid}'

# 切り抜きの時間(分)
clip_minutes = 10

# 一本の動画から切り抜く切り抜きの数
midokoro_count = 5

# エラー回避の繰り返し回数(多すぎるとyoutubeに怒られる)
ite = 200


# == 定数 ===================================================================================

# 日付の取得
today = datetime.today()
today = datetime.strftime(today, '%Y-%m-%dT00:00:00Z')


# == コメント取得，見どころ解析，切り抜き ===================================================================================

# == コメント取得 ===================================================================================

def get_comment(s):
    try:
        return s['replayChatItemAction']['actions'][0]['addChatItemAction']['item']['liveChatTextMessageRenderer']['message']['runs'][0]['text']
    except KeyError:
        return np.nan

def get_time(s):
    try:
        return s['replayChatItemAction']['videoOffsetTimeMsec']
    except KeyError:
        return np.nan


# エラー対策用の For : できないときとできるときがあるため
for _ in range(ite):

    dict_str = ""
    next_url = ""
    comment_data = []
    session = requests.Session()
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 6.2; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/32.0.1667.0 Safari/537.36'}

    html = requests.get(target_url)
    soup = BeautifulSoup(html.text, "html.parser")

    for iframe in soup.find_all("iframe"):
        if("live_chat_replay" in iframe["src"]):
            next_url= iframe["src"]

    while(1):
        try:
            html = session.get(next_url, headers=headers)
            soup = BeautifulSoup(html.text,"lxml")

            for scrp in soup.find_all("script"):
                if "window[\"ytInitialData\"]" in scrp.text:
                    dict_str = scrp.text.split(" = ")[1]

            dict_str = dict_str.replace("false","False")
            dict_str = dict_str.replace("true","True")

            dict_str = dict_str.rstrip("  \n;")
            dics = eval(dict_str)

            continue_url = dics["continuationContents"]["liveChatContinuation"]["continuations"][0]["liveChatReplayContinuationData"]["continuation"]
            next_url = "https://www.youtube.com/live_chat_replay?continuation=" + continue_url
            for samp in dics["continuationContents"]["liveChatContinuation"]["actions"][1:]:
                comment_data.append(str(samp)+"\n")
        except:
            break

    comment_data = pd.DataFrame(comment_data)

    try: 
        comment_data = comment_data[0].apply(ast.literal_eval)
    except KeyError: 
        continue

    comment = pd.DataFrame()
    comment['comment'] = comment_data.apply(get_comment)
    comment['time'] = comment_data.apply(get_time)
    comment.dropna(inplace=True)

    comment['time'] = (comment['time'].astype(int)/1000).astype(int)
    comment.sort_values('time', inplace=True)


    # == 見どころ解析 ===================================================================================

    # 草情報の追加
    # 空の場合がある
    try:
        comment['kusa'] = ((comment['comment'].str.contains('w')) |
                            (comment['comment'].str.contains('W')) |
                            (comment['comment'].str.contains('ｗ')) |
                            (comment['comment'].str.contains('W')) |
                            (comment['comment'].str.contains('笑')) |
                            (comment['comment'].str.contains('草'))).astype(int)
    except AttributeError:
        pass

    comment['count'] = 1

    # 集計する時間帯の作成

    last_time = comment['time'].max()+1

    tmp = pd.DataFrame(np.array(range(last_time)))
    tmp['range'] = np.nan
    range_sec = 15

    for i in range(int(len(tmp)/range_sec)+1):
        split = i*range_sec
        tmp.loc[split:split+range_sec, 'range'] = i

    tmp_dict = tmp.set_index(0).to_dict()['range']

    comment['label'] = comment['time'].map(lambda x: tmp_dict[x])

    comment_agg = comment[['label', 'kusa', 'count']].groupby('label').sum()
    comment_agg['kusa'] = (comment_agg['kusa'] / comment_agg['kusa'].max() + comment_agg['count'] / comment_agg['count'].max()) / 2

    comment_agg.reset_index(inplace=True)

    midokoro = comment_agg[['label', 'kusa']].sort_values('kusa', ascending=False).iloc[:5, :]
    midokoro['label'] = midokoro['label']*15
    midokoro['start'] = midokoro['label'] - 1 * clip_minutes * 60 / 2
    midokoro['end'] = midokoro['label'] + 1 * clip_minutes * 60 / 2
    midokoro.loc[midokoro['start']<0, 'start'] = 0

    # 見どころの重複を削除

    midokoro_top = pd.DataFrame(columns=midokoro.columns)

    i = 0
    while 1==1:
        try:
            tmp = midokoro.iloc[i]
        except:
            break
        label = tmp['label']
        if ~((midokoro_top['label']>label-1800)&
            (midokoro_top['label']<label+1800)).any():
            midokoro_top = pd.concat([midokoro_top, pd.DataFrame(tmp).T])  
        i += 1
        
    midokoro_top.sort_values('kusa', inplace=True)
    midokoro_top.reset_index(drop=True,inplace=True)
    

    # == 動画ダウンロード ===================================================================================

    try:
        yt = YouTube(target_url)
    except KeyError:
        continue

    yt_stream = yt.streams.filter(progressive=True).desc().first()
    yt_stream.download(f'./tmp/{vid}/')


    # == 切り抜き ===================================================================================

    for i in tqdm(midokoro_top.index):
        tmp = midokoro_top.iloc[i]
        
        # 動画の読み込み
        try: video = VideoFileClip(f'./tmp/{vid}/{yt_stream.title}.mp4')
        except OSError: 
            continue
            
        # 切り抜き，保存
        try:
            video = video.subclip(tmp['start'], tmp['end'])
            video.write_videofile(f"./result/{str(today)[0:10]}/{vid}_{i}.mp4",fps=30)
        except OSError:
            # TODO: なにこれ
            continue

    break

shutil.rmtree('./tmp')
os.mkdir('./tmp')
