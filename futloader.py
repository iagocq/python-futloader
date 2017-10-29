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
import collections

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


# From https://stackoverflow.com/a/566752
def _unix_get_terminal_size():
    import os
    env = os.environ
    def ioctl_GWINSZ(fd):
        try:
            import fcntl, termios, struct, os
            cr = struct.unpack('hh', fcntl.ioctl(fd, termios.TIOCGWINSZ,
        '1234'))
        except:
            return
        return cr
    cr = ioctl_GWINSZ(0) or ioctl_GWINSZ(1) or ioctl_GWINSZ(2)
    if not cr:
        try:
            fd = os.open(os.ctermid(), os.O_RDONLY)
            cr = ioctl_GWINSZ(fd)
            os.close(fd)
        except:
            pass
    if not cr:
        cr = (env.get('LINES', 25), env.get('COLUMNS', 80))
    return int(cr[1]), int(cr[0])


# From https://gist.github.com/jtriley/1108174
def _nt_get_terminal_size():
    try:
        from ctypes import windll, create_string_buffer
        # stdin handle is -10
        # stdout handle is -11
        # stderr handle is -12
        h = windll.kernel32.GetStdHandle(-12)
        csbi = create_string_buffer(22)
        res = windll.kernel32.GetConsoleScreenBufferInfo(h, csbi)
        if res:
            (bufx, bufy, curx, cury, wattr,
             left, top, right, bottom,
             maxx, maxy) = struct.unpack("hhhhHhhhhhh", csbi.raw)
            sizex = right - left + 1
            sizey = bottom - top + 1
            return sizex, sizey
    except:
        pass


def get_terminal_size():
    if os.name == 'nt':
        return _nt_get_terminal_size()
    elif os.name == 'posix':
        return _unix_get_terminal_size()


# Bytes to Human-Readable. Credits to https://stackoverflow.com/a/1094933
def sizeof_fmt(num, suffix='B'):
    for unit in ['', 'Ki', 'Mi', 'Gi', 'Ti', 'Pi', 'Ei', 'Zi']:
        if abs(num) < 1024.0:
            return "%3.2f%s%s" % (num, unit, suffix)
        num /= 1024.0
    return "%.2f%s%s" % (num, 'Yi', suffix)


# Hooked reports. Credits to https://stackoverflow.com/a/2030027
# Idea for a progress bar came from https://github.com/galeo/pyflit
# I didn't sww any of the code, just got the idea
def report_progress(bytes_so_far, chunk_size, total_size=None, extra='', bar_size=-1):
    width, height = get_terminal_size()

    percent = round(bytes_so_far / total_size * 100, 2) if bytes_so_far and total_size else '??.??'
    total_size = sizeof_fmt(total_size) if total_size else '?'
    bytes_so_far = sizeof_fmt(bytes_so_far) if bytes_so_far else '?'

    if isinstance(percent, float) or isinstance(percent, int):
        if bar_size == -1:
            bar_size = width - 55
        cbar = int(percent / (100 / bar_size))
        bar = '[' + ('#' * cbar) + ('-' * (bar_size - cbar)) + ']'
        percent = '%.2f' % percent
    else:
        bar = '[' + '-' * bar_size + ']'
    print('\r%s Downloaded %s of %s (%s%%) %s     ' % (bar,
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
                if isinstance(thread, collections.Iterable):
                    if thread[2]:
                        dones += 1
            
            if dones == len(thread_data):
                break
            
            for downloaded in thread_data:
                if isinstance(downloaded, collections.Iterable):
                    total_bytes_so_far += downloaded[0]
            
            report_progress(total_bytes_so_far, chunk_size, total_size, 'T', bar_size)
        except Exception as e:
            time.sleep(1)
            print(e)


# The code for multithreaded download was addapted
# from http://www.geeksforgeeks.org/simple-multithreaded-download-manager-in-python/
def download_url_segment(start, end, url, filename, chunk_size, thread_number):
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


def normal_download(request, destination, filename, chunk_size, size,
                    bar_size, status, verbose, report_hook=report_progress):
    bytes_so_far = 0
    st = time.time()
    
    with open(os.path.join(destination, filename), 'wb') as f:
        while True:
            chunk = request.read(chunk_size)
            bytes_so_far += len(chunk)
            
            if not chunk:
                break
            
            if verbose or status:
                report_hook(bytes_so_far, chunk_size, size, '', bar_size)
            
            f.write(chunk)
    
    if verbose or status:
        print('\nDownloaded ' + sizeof_fmt(bytes_so_far))


def segmented_download(url, destination, filename, threads,
                       size, bar_size, chunk_size, status, verbose):

    global thread_data

    with open(os.path.join(destination, filename), 'wb') as fp:
        fp.write(b'\0' * size)
    
    part = int(size / threads)
    thread_data = [_ for _ in range(threads)]
    
    for i in range(threads):
        start = part * i
        end = start + part
        t = threading.Thread(target=download_url_segment,
                             args=(start, end, url, os.path.join(destination, filename), chunk_size, i))
        t.setDaemon(True)
        t.start()
    
    if status or verbose:
        t = threading.Thread(target=thread_report, args=(chunk_size, size, bar_size))
        t.setDaemon(True)
        t.start()
    main_thread = threading.current_thread()
    
    for t in threading.enumerate():
        if t == main_thread:
            continue
        t.join()
    
    if verbose or status:
        print()


def download_url(url, threads=None, chunk_size=8 * 1024, verbose=False, destination=None,
                 threshold=None, bar_size=40, status=False, report_hook=report_progress):
    # Start request
    r = urlopen(url)
    filename = urlparse(url)
    filename = os.path.basename(filename.path)

    size = None
    allow_range = False
    part = None
    if not destination:
        destination = '.'

    # Custom filename
    if 'Content-Disposition' in r.headers:
        cont = r.headers['Content-Disposition']
        if 'filename' in cont:
            filename = re.findall('filename=([^\s]+)', cont)[0]

    # Segmented downloads
    if 'Accept-Ranges' in r.headers:
        sups = r.headers['Accept-Ranges']
        allow_range = sups != 'none' and sups == 'bytes'

    # File size
    if 'Content-Length' in r.headers:
        size = int(r.headers['Content-Length'].strip())

    # Print status
    if verbose or status:
        print('Downloading ' + filename, end='')
    if verbose:
        print(' (from ' + url + ')', end='')
    elif status:
        print()

    # Normal download switch
    normal = False
    if size and threshold:
        if size < threshold:
            normal = True

    if not threads or normal:
        pass
    
    elif allow_range:
        segmented_download(url, destination, filename, threads, size, bar_size, chunk_size, status, verbose)
        return
    
    normal_download(r, destination, filename, chunk_size, size, bar_size, status, verbose)


def main():
    parser = argparse.ArgumentParser(description='A file downloader written in Python')
    parser.add_argument('urls', metavar='URL', type=str, nargs='+',
                        help='the URL(s) of the file(s) to be downloaded')
    
    parser.add_argument('-d', metavar='destination', type=str, dest='dest', default='.',
                        help='directory to save the file(s)')
    
    parser.add_argument('-t', metavar='threads', type=int, dest='threads', default=None,
                        help='number of threads to run when partial download is allowed (default 0)')
    
    parser.add_argument('-v', action='store_true', default=False, dest='verbose',
                        help='verbose mode')
    
    parser.add_argument('-s', action='store_true', default=False, dest='status',
                        help='show download status and progress')
    
    parser.add_argument('-c', metavar='chunk-size', type=int, dest='chunk_size', default=8096,
                        help='the size of each byte chunk (default 8096 / 8KiB)')
    
    parser.add_argument('-b', metavar='bar-size', type=int, dest='bar_size', default=-1,
                        help='the size of the progress bar, excluding the "[" and "]" (default -1, fit most)')
    
    parser.add_argument('-f', action='store_true', default=False, dest='force_no_thread',
                        help='Does not use multi-segmented download even if the URL supports it')
    
    parser.add_argument('--check-partial', action='store_true', default=False, dest='check_partial',
                        help='check if partial download is allowed for given URL(s)')
    
    parser.add_argument('--user-agent',
                        default='Mozilla/5.0 (Windows NT 6.1; Win64; x64) AppleWebKit/537.36 ' + 
                        '(KHTML, like Gecko) Chrome/40.0.2214.85 Safari/537.36',
                        dest='user_agent', help='change the default user-agent', metavar='user-agent', type=str)
    
    parser.add_argument('--threshold', default=1048576, dest='threshold', type=int, metavar='threshold',
                        help='how much bytes are needed to start a threaded download (default 1048576 / 1MiB)')
    
    parser.set_defaults(func=run)
    args = parser.parse_args()
    args.func(args)


def run(args):
    if args.threads is not None:
        if args.threads < 0:
            print('Minimum ammount of threads is 0')
            exit(0)
        if args.threads == 0:
            args.threads = None

    if args.force_no_thread:
        args.threads = None

    if args.chunk_size < 1:
        print('Minimum chunk size is 1')
        exit(0)

    if args.bar_size < 1 and args.bar_size != -1:
        print('Minimum bar size is 1 or -1')
        exit(0)

    if not os.path.isdir(args.dest):
        if not os.path.exists(args.dest):
            os.mkdir(args.dest)
        else:
            print('Destination already exists: file')

    for url in args.urls:
        download_url(url, args.threads, args.chunk_size, args.verbose,
                     args.dest, args.threshold, args.bar_size, args.status)


if __name__ == '__main__':
    # download_url('http://speedtest.ftp.otenet.gr/files/test100Mb.db', threads=16, verbose=True)
    main()
