from flask import Flask, render_template, request, redirect, url_for, send_from_directory, jsonify
import os
import sqlite3
from werkzeug.utils import secure_filename
from datetime import datetime

app = Flask(__name__)

# 설정
UPLOAD_FOLDER = 'uploads'
ALLOWED_EXTENSIONS = {'txt'}
DATABASE = 'library.db'

app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

def init_db():
    with sqlite3.connect(DATABASE) as conn:
        c = conn.cursor()
        # 계층형 카테고리 테이블
        c.execute('''
            CREATE TABLE IF NOT EXISTS categories
            (id INTEGER PRIMARY KEY AUTOINCREMENT,
             name TEXT NOT NULL,
             parent_id INTEGER,
             path TEXT NOT NULL,
             level INTEGER NOT NULL,
             FOREIGN KEY (parent_id) REFERENCES categories (id))
        ''')
        # 파일 테이블
        c.execute('''
            CREATE TABLE IF NOT EXISTS files
            (id INTEGER PRIMARY KEY AUTOINCREMENT,
             filename TEXT NOT NULL,
             category_id INTEGER,
             upload_date TEXT NOT NULL,
             FOREIGN KEY (category_id) REFERENCES categories (id))
        ''')
        conn.commit()

def get_category_path(category_id):
    with sqlite3.connect(DATABASE) as conn:
        c = conn.cursor()
        c.execute('SELECT path FROM categories WHERE id = ?', (category_id,))
        result = c.fetchone()
        return result[0] if result else ''

def get_category_tree():
    with sqlite3.connect(DATABASE) as conn:
        c = conn.cursor()
        c.execute('SELECT id, name, parent_id, path, level FROM categories ORDER BY path')
        categories = c.fetchall()
        
        # 트리 구조 생성
        tree = []
        lookup = {}
        
        for cat in categories:
            category = {
                'id': cat[0],
                'name': cat[1],
                'parent_id': cat[2],
                'path': cat[3],
                'level': cat[4],
                'children': []
            }
            lookup[cat[0]] = category
            
            if cat[2] is None:  # 최상위 카테고리
                tree.append(category)
            else:  # 하위 카테고리
                parent = lookup.get(cat[2])
                if parent:
                    parent['children'].append(category)
                    
        return tree

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/upload')
def upload():
    category_tree = get_category_tree()
    return render_template('upload.html', categories=category_tree)

@app.route('/category')
def category():
    category_tree = get_category_tree()
    return render_template('category.html', categories=category_tree)

@app.route('/list')
def list_files():
    category_id = request.args.get('category', type=int)
    category_tree = get_category_tree()
    
    with sqlite3.connect(DATABASE) as conn:
        c = conn.cursor()
        
        if category_id:
            # 현재 카테고리와 모든 하위 카테고리의 파일 가져오기
            category_path = get_category_path(category_id)
            c.execute('''
                SELECT files.*, categories.name, categories.path
                FROM files 
                LEFT JOIN categories ON files.category_id = categories.id
                WHERE categories.path LIKE ?
                ORDER BY upload_date DESC
            ''', (f'{category_path}%',))
        else:
            c.execute('''
                SELECT files.*, categories.name, categories.path
                FROM files 
                LEFT JOIN categories ON files.category_id = categories.id
                ORDER BY upload_date DESC
            ''')
        files = c.fetchall()
        
    return render_template('list.html', files=files, categories=category_tree, selected_category=category_id)

@app.route('/category', methods=['POST'])
def add_category():
    category_name = request.form.get('category_name')
    parent_id = request.form.get('parent_id', type=int)
    
    if category_name:
        with sqlite3.connect(DATABASE) as conn:
            c = conn.cursor()
            try:
                if parent_id:
                    # 부모 카테고리 정보 가져오기
                    c.execute('SELECT path, level FROM categories WHERE id = ?', (parent_id,))
                    parent = c.fetchone()
                    if parent:
                        path = f"{parent[0]}/{category_name}"
                        level = parent[1] + 1
                    else:
                        path = category_name
                        level = 0
                else:
                    path = category_name
                    level = 0
                
                c.execute('''
                    INSERT INTO categories (name, parent_id, path, level)
                    VALUES (?, ?, ?, ?)
                ''', (category_name, parent_id, path, level))
                conn.commit()
                
            except sqlite3.IntegrityError:
                pass
    return redirect(url_for('category'))

@app.route('/category/<int:category_id>', methods=['DELETE'])
def delete_category(category_id):
    with sqlite3.connect(DATABASE) as conn:
        c = conn.cursor()
        # 하위 카테고리가 있는지 확인
        c.execute('SELECT COUNT(*) FROM categories WHERE parent_id = ?', (category_id,))
        if c.fetchone()[0] > 0:
            return jsonify({'error': '하위 카테고리가 있는 카테고리는 삭제할 수 없습니다'}), 400
        
        # 카테고리에 속한 파일이 있는지 확인
        c.execute('SELECT COUNT(*) FROM files WHERE category_id = ?', (category_id,))
        if c.fetchone()[0] > 0:
            return jsonify({'error': '파일이 있는 카테고리는 삭제할 수 없습니다'}), 400
        
        c.execute('DELETE FROM categories WHERE id = ?', (category_id,))
        conn.commit()
        return jsonify({'success': True})

@app.route('/upload', methods=['POST'])
def upload_file():
    if 'file' not in request.files:
        return redirect(url_for('upload'))
    
    file = request.files['file']
    category_id = request.form.get('category', type=int)
    
    if file.filename == '':
        return redirect(url_for('upload'))
    
    if file and allowed_file(file.filename):
        filename = secure_filename(file.filename)
        file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
        
        with sqlite3.connect(DATABASE) as conn:
            c = conn.cursor()
            c.execute(
                'INSERT INTO files (filename, category_id, upload_date) VALUES (?, ?, ?)',
                (filename, category_id, datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
            )
            conn.commit()
            
        return redirect(url_for('list_files'))
    return redirect(url_for('upload'))

@app.route('/read/<filename>')
def read_file(filename):
    try:
        with open(os.path.join(app.config['UPLOAD_FOLDER'], filename), 'r', encoding='utf-8') as f:
            content = f.read()
        return render_template('read.html', filename=filename, content=content)
    except Exception as e:
        return f"파일을 읽는 중 오류가 발생했습니다: {str(e)}"

@app.route('/download/<filename>')
def download_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

@app.route('/update_category/<int:file_id>', methods=['POST'])
def update_category(file_id):
    category_id = request.form.get('category_id', type=int)
    with sqlite3.connect(DATABASE) as conn:
        c = conn.cursor()
        c.execute('UPDATE files SET category_id = ? WHERE id = ?', (category_id, file_id))
        conn.commit()
    return redirect(url_for('list_files'))

if __name__ == '__main__':
    init_db()
    app.run(debug=True)
