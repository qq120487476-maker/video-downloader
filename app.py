from flask import Flask, request, jsonify, send_file, render_template, after_this_request
import yt_dlp
import os
import uuid
import tempfile
import shutil
import threading
import imageio_ffmpeg

FFMPEG_PATH = imageio_ffmpeg.get_ffmpeg_exe()

app = Flask(__name__)

# job_id -> {status, file, filename, error, temp_dir}
jobs = {}
jobs_lock = threading.Lock()


def _headers():
    return {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
        'Referer': 'https://www.bilibili.com',
        'Origin': 'https://www.bilibili.com',
    }


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/api/info', methods=['POST'])
def get_info():
    data = request.get_json()
    url = data.get('url', '').strip()
    if not url:
        return jsonify({'error': '请提供视频链接'}), 400

    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'ffmpeg_location': FFMPEG_PATH,
        'http_headers': _headers(),
        'extractor_args': {'bilibili': {'prefer_multi_flv': ['True']}},
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)

        formats = []
        seen_heights = set()
        if 'formats' in info:
            for f in reversed(info['formats']):
                height = f.get('height')
                vcodec = f.get('vcodec', 'none')
                if vcodec and vcodec != 'none' and height and height not in seen_heights:
                    seen_heights.add(height)
                    formats.append({
                        'format_id': f'bestvideo[height<={height}]+bestaudio/best[height<={height}]/best',
                        'label': f'{height}p',
                        'height': height,
                    })

        if not formats:
            formats = [{'format_id': 'best', 'label': '最佳画质', 'height': 9999}]
        else:
            formats.sort(key=lambda x: x['height'], reverse=True)
            formats.insert(0, {'format_id': 'bestvideo+bestaudio/best', 'label': '最佳画质', 'height': 99999})

        duration = info.get('duration', 0)
        duration_str = f'{int(duration//60)}:{int(duration%60):02d}' if duration else ''

        return jsonify({
            'title': info.get('title', '未知标题'),
            'thumbnail': info.get('thumbnail', ''),
            'duration': duration_str,
            'uploader': info.get('uploader', ''),
            'formats': formats,
        })
    except Exception as e:
        return jsonify({'error': f'解析失败: {str(e)}'}), 400


def _do_download(job_id, url, format_id, title):
    temp_dir = tempfile.mkdtemp()
    safe_name = str(uuid.uuid4())

    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'ffmpeg_location': FFMPEG_PATH,
        'outtmpl': os.path.join(temp_dir, f'{safe_name}.%(ext)s'),
        'format': format_id,
        'merge_output_format': 'mp4',
        'socket_timeout': 60,
        'retries': 10,
        'fragment_retries': 10,
        'http_headers': _headers(),
        'extractor_args': {'bilibili': {'prefer_multi_flv': ['True']}},
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.extract_info(url, download=True)

        # Prefer the expected merged mp4 file
        expected = os.path.join(temp_dir, f'{safe_name}.mp4')
        if os.path.exists(expected) and os.path.getsize(expected) > 1024:
            filepath = expected
            ext = '.mp4'
        else:
            # Fallback: pick the largest non-temp file
            candidates = [
                os.path.join(temp_dir, f) for f in os.listdir(temp_dir)
                if not f.endswith(('.part', '.ytdl', '.json'))
            ]
            if not candidates:
                raise Exception('下载完成但未找到文件')
            filepath = max(candidates, key=os.path.getsize)
            ext = os.path.splitext(filepath)[1]

        safe_title = "".join(c for c in title if c.isalnum() or c in ' ._-（）').strip() or 'video'
        filename = f'{safe_title}{ext}'

        with jobs_lock:
            jobs[job_id].update({'status': 'done', 'file': filepath, 'filename': filename, 'temp_dir': temp_dir})

    except Exception as e:
        shutil.rmtree(temp_dir, ignore_errors=True)
        with jobs_lock:
            jobs[job_id].update({'status': 'error', 'error': str(e)})


@app.route('/api/download', methods=['POST'])
def download():
    data = request.get_json()
    url = data.get('url', '').strip()
    format_id = data.get('format_id', 'bestvideo+bestaudio/best')
    title = data.get('title', 'video')

    if not url:
        return jsonify({'error': '请提供视频链接'}), 400

    job_id = str(uuid.uuid4())
    with jobs_lock:
        jobs[job_id] = {'status': 'downloading', 'file': None, 'filename': None, 'error': None, 'temp_dir': None}

    t = threading.Thread(target=_do_download, args=(job_id, url, format_id, title))
    t.daemon = True
    t.start()

    return jsonify({'job_id': job_id})


@app.route('/api/status/<job_id>')
def job_status(job_id):
    with jobs_lock:
        job = jobs.get(job_id)
    if not job:
        return jsonify({'status': 'not_found'}), 404
    return jsonify({'status': job['status'], 'error': job.get('error', '')})


@app.route('/api/file/<job_id>')
def get_file(job_id):
    with jobs_lock:
        job = jobs.get(job_id)

    if not job or job['status'] != 'done':
        return jsonify({'error': '文件未就绪'}), 404

    filepath = job['file']
    filename = job['filename']
    temp_dir = job['temp_dir']

    @after_this_request
    def cleanup(response):
        shutil.rmtree(temp_dir, ignore_errors=True)
        with jobs_lock:
            jobs.pop(job_id, None)
        return response

    return send_file(filepath, as_attachment=True, download_name=filename)


if __name__ == '__main__':
    import time
    import webbrowser

    def open_browser():
        time.sleep(1.5)
        webbrowser.open('http://localhost:5000')

    threading.Thread(target=open_browser, daemon=True).start()
    print("视频下载器已启动：http://localhost:5000")
    app.run(debug=False, port=5000)
