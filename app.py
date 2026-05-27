from flask import Flask, request, jsonify, send_file, render_template, after_this_request
import yt_dlp
import os
import uuid
import tempfile
import shutil

app = Flask(__name__)


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
        if duration:
            minutes = int(duration // 60)
            seconds = int(duration % 60)
            duration_str = f'{minutes}:{seconds:02d}'
        else:
            duration_str = ''

        return jsonify({
            'title': info.get('title', '未知标题'),
            'thumbnail': info.get('thumbnail', ''),
            'duration': duration_str,
            'uploader': info.get('uploader', ''),
            'formats': formats,
        })
    except Exception as e:
        return jsonify({'error': f'解析失败: {str(e)}'}), 400


@app.route('/api/download', methods=['POST'])
def download():
    data = request.get_json()
    url = data.get('url', '').strip()
    format_id = data.get('format_id', 'bestvideo+bestaudio/best')
    title = data.get('title', 'video')

    if not url:
        return jsonify({'error': '请提供视频链接'}), 400

    temp_dir = tempfile.mkdtemp()
    safe_name = str(uuid.uuid4())

    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'outtmpl': os.path.join(temp_dir, f'{safe_name}.%(ext)s'),
        'format': format_id,
        'merge_output_format': 'mp4',
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.extract_info(url, download=True)

        files = os.listdir(temp_dir)
        if not files:
            shutil.rmtree(temp_dir, ignore_errors=True)
            return jsonify({'error': '下载失败，未找到文件'}), 500

        filepath = os.path.join(temp_dir, files[0])
        ext = os.path.splitext(files[0])[1]

        safe_title = "".join(c for c in title if c.isalnum() or c in ' ._-（）').strip()
        if not safe_title:
            safe_title = 'video'
        download_name = f'{safe_title}{ext}'

        @after_this_request
        def cleanup(response):
            shutil.rmtree(temp_dir, ignore_errors=True)
            return response

        return send_file(filepath, as_attachment=True, download_name=download_name)

    except Exception as e:
        shutil.rmtree(temp_dir, ignore_errors=True)
        return jsonify({'error': f'下载失败: {str(e)}'}), 400


if __name__ == '__main__':
    import threading
    import time
    import webbrowser

    def open_browser():
        time.sleep(1.5)
        webbrowser.open('http://localhost:5000')

    threading.Thread(target=open_browser, daemon=True).start()
    print("视频下载器已启动：http://localhost:5000")
    app.run(debug=False, port=5000)
