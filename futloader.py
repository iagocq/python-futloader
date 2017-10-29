#!/usr/bin/env python

#   This program is free software: you can redistribute it and/or modify
#   it under the terms of the GNU General Public License as published by
#   the Free Software Foundation, either version 3 of the License, or
#   (at your option) any later version.
#
#   This program is distributed in the hope that it will be useful,
#   but WITHOUT ANY WARRANTY; without even the implied warranty of
#   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#   GNU General Public License for more details.
#
#   You should have received a copy of the GNU General Public License
#   along with this program.  If not, see <http://www.gnu.org/licenses/>.



#   Author: iagoq

from __future__ import print_function
from __future__ import division
from math import ceil
import argparse
import re
import os
import time
import sys
import threading

try:
    from urllib.parse import urlparse, urlencode
    from urllib.request import urlopen, Request
    from urllib.error import HTTPError
except ImportError:
    from urlparse import urlparse
    from urllib import urlencode
    from urllib2 import urlopen, Request, HTTPError

thread_data = []
lock = threading.Lock()


# Bytes to Human-Readable. Credits to https://stackoverflow.com/a/1094933
def sizeof_fmt(num, suffix='B'):
    for unit in ['','Ki','Mi','Gi','Ti','Pi','Ei','Zi']:
        if abs(num) < 1024.0:
            return "%3.2f%s%s" % (num, unit, suffix)
        num /= 1024.0
    return "%.2f%s%s" % (num, 'Yi', suffix)


# Hooked reports. Credits to https://stackoverflow.com/a/2030027
# Idea for a progress bar came from https://github.com/galeo/pyflit
# I didn't sww any of the code, just got the idea
def report_progress(bytes_so_far, chunk_size, total_size=None, extra='', bar_size=40):
    percent = round(bytes_so_far / total_size * 100, 2) if bytes_so_far and total_size else '?'
    total_size = sizeof_fmt(total_size) if total_size else '?'
    bytes_so_far = sizeof_fmt(bytes_so_far) if bytes_so_far else '?'
    if isinstance(percent, float) or isinstance(percent, int):
        cbar = 100 / bar_size
        ts = int(percent / cbar)
        bar = '[' + ('#' * ts) + ('-' * (bar_size - ts)) + ']'
    else:
        bar = '[' + '-' * bar_size + ']'
    print('%s Downloaded %s of %s (%s%%) %s           \r' % (bar,
                                                             bytes_so_far,
                                                             total_size,
                                                             percent,
                                                             extra), end='')
    sys.stdout.flush()


def thread_report(chunk_size, total_size, bar_size=40):
    while True:
        try:
            total_bytes_so_far = 0
            dones = 0
            for thread in thread_data:
                if isinstance(thread, tuple):
                    if thread[2]:
                        dones += 1
            if dones == len(thread_data):
                break
            for downloaded in thread_data:
                if isinstance(downloaded, tuple):
                    total_bytes_so_far += downloaded[0]
            report_progress(total_bytes_so_far, chunk_size, total_size, 'T', bar_size)
            time.sleep(0.1)
        except Exception as e:
            print(e)


# The code for multithreaded download was addapted from http://www.geeksforgeeks.org/simple-multithreaded-download-manager-in-python/
def download_url_range(start, end, url, filename, chunk_size, thread_number):
    r = Request(url)
    r.add_header('Range', 'bytes=%d-%d' % (start, end))
    r = urlopen(r)
    bytes_so_far = 0
    with open(filename, 'r+b') as fp:
        fp.seek(start)
        try:
            while True:
                chunk = r.read(chunk_size)
                bytes_so_far += len(chunk)
                if not chunk:
                    break
                with lock:
                    thread_data[thread_number] = (bytes_so_far, end - start, False)
                    fp.write(chunk)
        except Exception as e:
            print(e)
    with lock:
        thread_data[thread_number] = (bytes_so_far, end - start, True)


def download_url(url, threads=None, chunk_size=8 * 1024, verbose=False, destination=None, threshold=None, bar_size=40, status=False, report_hook=report_progress):
    r = urlopen(url)
    fname = urlparse(url)
    fname = os.path.basename(fname.path)
    size = None
    allow_range = False
    part = None
    if not destination:
        destination = '.'
    if 'Content-Disposition' in r.headers:
        cont = r.headers['Content-Disposition']
        if 'filename' in cont:
            fname = re.findall('filename=([^\s]+)', cont)[0]

    if 'Accept-Ranges' in r.headers:
        sups = r.headers['Accept-Ranges']
        allow_range = sups != 'none' and sups == 'bytes'
                
    if 'Content-Length' in r.headers:
        size = int(r.headers['Content-Length'].strip())
    
    if verbose or status:
        print('Downloading ' + fname, end='')
    if verbose:
        print(' (from ' + url + ')', end='')
    elif status:
        print()
    normal = False
    if size and threshold:
        if size < threshold:
            normal = True
    bytes_so_far = 0
    st = time.time()
    if not threads or normal:
        pass
    elif allow_range:
        global thread_data
        with open(os.path.join(destination, fname), 'wb') as fp:
            fp.write(b'\0' * size)
        part = int(size / threads)
        thread_data = [_ for _ in range(threads)]
        for i in range(threads):
            start = part * i
            end = start + part
            t = threading.Thread(target=download_url_range, args=(start, end, url, os.path.join(destination, fname), chunk_size, i))
            t.setDaemon(True)
            t.start()
        if status or verbose:
            t = threading.Thread(target=thread_report, args=(chunk_size, size))
            t.setDaemon(True)
            t.start()
        main_thread = threading.current_thread()
        for t in threading.enumerate():
            if t == main_thread:
                continue
            t.join()
        if verbose or status:
            print()
        return
    with open(os.path.join(destination, fname), 'wb') as f:
        while True:
            chunk = r.read(chunk_size)
            bytes_so_far += len(chunk)
            if not chunk:
                break
            if verbose or status:
                report_hook(bytes_so_far, chunk_size, size)
            f.write(chunk)
    if verbose or status:
        print('\nDownloaded ' + sizeof_fmt(bytes_so_far))


def main():
    parser = argparse.ArgumentParser(description='A file downloader written in Python')
    parser.add_argument('urls', metavar='URL', type=str, nargs='+',
                        help='the URL(s) of the file(s) to be downloaded')
    parser.add_argument('-d', metavar='destination', type=str, dest='dest', default='.',
                        help='directory to save the file(s)')
    parser.add_argument('-t', metavar='threads', type=int, dest='threads', default=None,
                        help='number of threads to run when partial download is allowed (default 1)')
    parser.add_argument('-v', action='store_true', default=False, dest='verbose',
                        help='verbose mode')
    parser.add_argument('-s', action='store_true', default=False, dest='status',
                        help='show download status and progress')
    parser.add_argument('-c', metavar='chunk-size', type=int, dest='chunk_size', default=8096,
                        help='the size of each byte chunk (default 8096 / 8KiB)')
    parser.add_argument('-b', metavar='bar-size', type=int, dest='bar_size', default=40,
                        help='the size of the progress bar, excluding the "[" and "]" (default 40)')
    parser.add_argument('--check-partial', action='store_true', default=False, dest='check_partial',
                        help='check if partial download is allowed for given URL(s)')
    parser.add_argument('--user-agent', default="Mozilla/5.0 (Windows NT 6.1; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/40.0.2214.85 Safari/537.36",
                        dest='user_agent', help='change the default user-agent', metavar='user-agent', type=str)
    parser.add_argument('--threshold', default=1048576, dest='threshold', type=int, metavar='threshold',
                        help='how much bytes are needed to start a threaded download (default 1048576 / 1MiB)')
    parser.set_defaults(func=run)
    args = parser.parse_args()
    args.func(args)


def run(args):
    if args.threads is not None:
        if args.threads < 1:
            print('Minimum ammount of threads is 1')
            exit(0)
    if args.chunk_size < 1:
        print('Minimum chunk size is 1')
        exit(0)
    if args.bar_size < 1:
        print('Minimum bar size is 1')
        exit(0)
    if not os.path.isdir(args.dest):
        if not os.path.exists(args.dest):
            os.mkdir(args.dest)
        else:
            print('Destination already exists: file')
    for url in args.urls:
        download_url(url, args.threads, args.chunk_size, args.verbose, args.dest, args.threshold, args.bar_size, args.status)

if __name__ == '__main__':
    main()
#download_url('http://speedtest.ftp.otenet.gr/files/test100Mb.db', threads=16, verbose=True)
