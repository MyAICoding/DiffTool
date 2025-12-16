import os
import sys
import hashlib
import zipfile
import tempfile
import threading
import json
import webbrowser
import mimetypes
from difflib import SequenceMatcher
from datetime import datetime
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

# --- 核心逻辑部分 ---

class FileAnalyzer:
    def __init__(self):
        self.stop_event = threading.Event()

    def get_file_hash(self, filepath):
        """计算文件SHA256"""
        sha256_hash = hashlib.sha256()
        try:
            with open(filepath, "rb") as f:
                for byte_block in iter(lambda: f.read(4096), b""):
                    sha256_hash.update(byte_block)
            return sha256_hash.hexdigest()
        except Exception:
            return None

    def is_text_file(self, filepath):
        """简单判断是否为文本文件"""
        guess, _ = mimetypes.guess_type(filepath)
        if guess and guess.startswith('text'):
            return True
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                f.read(512)
                return True
        except:
            return False

    def get_text_similarity(self, file1, file2):
        """计算文本相似度"""
        try:
            with open(file1, 'r', encoding='utf-8', errors='ignore') as f1:
                text1 = f1.read()
            with open(file2, 'r', encoding='utf-8', errors='ignore') as f2:
                text2 = f2.read()
            return SequenceMatcher(None, text1, text2).ratio()
        except:
            return 0.0

    def extract_or_walk(self, target_path, temp_dir):
        """处理文件夹或压缩包"""
        file_map = {} 
        ext = os.path.splitext(target_path)[1].lower()
        is_archive = ext in ['.zip', '.ipa', '.apk', '.jar']
        
        scan_root = target_path
        if is_archive:
            try:
                extract_path = os.path.join(temp_dir, "extracted_" + os.path.basename(target_path) + "_" + str(hash(target_path)))
                os.makedirs(extract_path, exist_ok=True)
                with zipfile.ZipFile(target_path, 'r') as zip_ref:
                    zip_ref.extractall(extract_path)
                scan_root = extract_path
            except Exception as e:
                print(f"Error extracting {target_path}: {e}")
                return {}

        scan_root = os.path.abspath(scan_root)
        for root, _, files in os.walk(scan_root):
            for file in files:
                full_path = os.path.join(root, file)
                rel_path = os.path.relpath(full_path, scan_root)
                rel_path = rel_path.replace("\\", "/")
                file_map[rel_path] = full_path
        return file_map

    def compare(self, path_a, path_b, callback_progress=None):
        result = {
            "summary": {"same": 0, "diff": 0, "added": 0, "deleted": 0, "total": 0},
            "details": []
        }

        with tempfile.TemporaryDirectory() as temp_root:
            if callback_progress: callback_progress("正在分析源文件 A...")
            files_a = self.extract_or_walk(path_a, temp_root)
            
            if callback_progress: callback_progress("正在分析目标文件 B...")
            files_b = self.extract_or_walk(path_b, temp_root)

            all_keys = set(files_a.keys()) | set(files_b.keys())
            total_files = len(all_keys)
            processed = 0

            if callback_progress: callback_progress(f"开始对比 {total_files} 个文件...")

            for rel_path in sorted(list(all_keys)):
                processed += 1
                if callback_progress and processed % 20 == 0:
                    callback_progress(f"对比中... {processed}/{total_files}")

                item = {
                    "path": rel_path,
                    "status": "",
                    "similarity": 0.0, # 存储为数字方便排序
                    "similarity_str": "0%",
                    "size_a": 0,
                    "size_b": 0,
                    "size_diff": 0,
                    "type_category": "unknown" # diff, added, deleted, same
                }

                in_a = rel_path in files_a
                in_b = rel_path in files_b
                
                p_a = files_a.get(rel_path)
                p_b = files_b.get(rel_path)

                if in_a: item["size_a"] = os.path.getsize(p_a)
                if in_b: item["size_b"] = os.path.getsize(p_b)

                if in_a and in_b:
                    item["size_diff"] = item["size_b"] - item["size_a"]
                    
                    hash_a = self.get_file_hash(p_a)
                    hash_b = self.get_file_hash(p_b)

                    if hash_a == hash_b:
                        item["status"] = "相同"
                        item["type_category"] = "same"
                        item["similarity"] = 1.0
                        item["similarity_str"] = "100%"
                        result["summary"]["same"] += 1
                    else:
                        item["status"] = "差异"
                        item["type_category"] = "diff"
                        result["summary"]["diff"] += 1
                        if self.is_text_file(p_a) and self.is_text_file(p_b):
                            sim = self.get_text_similarity(p_a, p_b)
                            item["similarity"] = sim
                            item["similarity_str"] = f"{sim:.1%}"
                        else:
                            item["similarity"] = 0.0
                            item["similarity_str"] = "Hash不同"
                
                elif in_a and not in_b:
                    item["status"] = "已删除"
                    item["type_category"] = "deleted"
                    item["size_diff"] = -item["size_a"]
                    result["summary"]["deleted"] += 1
                
                elif not in_a and in_b:
                    item["status"] = "新增"
                    item["type_category"] = "added"
                    item["size_diff"] = item["size_b"]
                    result["summary"]["added"] += 1

                result["details"].append(item)

            result["summary"]["total"] = total_files
            return result

# --- 报告生成逻辑 ---

class ReportGenerator:
    @staticmethod
    def generate_html(result_data, output_path):
        json_data = json.dumps(result_data, ensure_ascii=False)
        
        # 将数据预分类，方便 HTML 渲染
        html_content = f"""
        <!DOCTYPE html>
        <html lang="zh-CN">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>文件对比深度分析报告</title>
            <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
            <style>
                body {{ font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background: #f0f2f5; margin: 0; padding: 20px; }}
                .container {{ max-width: 1400px; margin: 0 auto; background: white; padding: 25px; border-radius: 10px; box-shadow: 0 4px 6px rgba(0,0,0,0.1); }}
                h1 {{ color: #2c3e50; text-align: center; margin-bottom: 30px; }}
                
                /* 概览区域 */
                .dashboard {{ display: flex; flex-wrap: wrap; justify-content: space-around; align-items: center; margin-bottom: 30px; padding-bottom: 20px; border-bottom: 2px solid #eee; }}
                .chart-box {{ width: 300px; height: 300px; }}
                .stats-box {{ font-size: 16px; line-height: 1.8; }}
                .stat-item {{ display: flex; align-items: center; justify-content: space-between; width: 250px; }}
                .badge {{ padding: 2px 8px; border-radius: 4px; color: white; font-size: 14px; font-weight: bold; }}
                
                /* 选项卡样式 */
                .tab {{ overflow: hidden; border-bottom: 1px solid #ccc; margin-bottom: 15px; }}
                .tab button {{ background-color: inherit; float: left; border: none; outline: none; cursor: pointer; padding: 14px 20px; transition: 0.3s; font-size: 16px; color: #555; font-weight: 600; }}
                .tab button:hover {{ background-color: #ddd; }}
                .tab button.active {{ background-color: #007bff; color: white; }}
                
                /* 表格内容 */
                .tabcontent {{ display: none; animation: fadeEffect 0.5s; }}
                @keyframes fadeEffect {{ from {{opacity: 0;}} to {{opacity: 1;}} }}
                
                table {{ width: 100%; border-collapse: collapse; font-size: 13px; table-layout: fixed; }}
                th, td {{ border: 1px solid #e1e4e8; padding: 10px; text-align: left; word-break: break-all; }}
                th {{ background-color: #f8f9fa; color: #333; position: sticky; top: 0; }}
                tr:nth-child(even) {{ background-color: #fcfcfc; }}
                tr:hover {{ background-color: #f1f1f1; }}
                
                .col-path {{ width: 50%; }}
                .col-status {{ width: 10%; }}
                .col-sim {{ width: 10%; }}
                .col-size {{ width: 10%; }}
                
                .c-diff {{ color: #fd7e14; }}
                .c-add {{ color: #007bff; }}
                .c-del {{ color: #dc3545; }}
                .c-same {{ color: #28a745; }}
            </style>
        </head>
        <body>
            <div class="container">
                <h1>文件对比分析报告</h1>
                
                <div class="dashboard">
                    <div class="chart-box">
                        <canvas id="diffChart"></canvas>
                    </div>
                    <div class="stats-box">
                        <h3>统计摘要</h3>
                        <div class="stat-item">总文件数: <span id="s-total" style="font-weight:bold"></span></div>
                        <div class="stat-item"><span>内容差异:</span> <span class="badge" style="background:#fd7e14" id="s-diff"></span></div>
                        <div class="stat-item"><span>新增文件:</span> <span class="badge" style="background:#007bff" id="s-added"></span></div>
                        <div class="stat-item"><span>删除文件:</span> <span class="badge" style="background:#dc3545" id="s-deleted"></span></div>
                        <div class="stat-item"><span>完全相同:</span> <span class="badge" style="background:#28a745" id="s-same"></span></div>
                    </div>
                </div>

                <!-- 选项卡 -->
                <div class="tab">
                    <button class="tablinks active" onclick="openTab(event, 'TabDiff')">⚠️ 内容差异</button>
                    <button class="tablinks" onclick="openTab(event, 'TabAdd')">🔵 新增文件</button>
                    <button class="tablinks" onclick="openTab(event, 'TabDel')">🔴 删除文件</button>
                    <button class="tablinks" onclick="openTab(event, 'TabSame')">✅ 完全相同</button>
                </div>

                <div id="TabDiff" class="tabcontent" style="display:block;"></div>
                <div id="TabAdd" class="tabcontent"></div>
                <div id="TabDel" class="tabcontent"></div>
                <div id="TabSame" class="tabcontent"></div>

            </div>

            <script>
                const data = {json_data};
                
                // 填充统计
                document.getElementById('s-total').innerText = data.summary.total;
                document.getElementById('s-same').innerText = data.summary.same;
                document.getElementById('s-diff').innerText = data.summary.diff;
                document.getElementById('s-added').innerText = data.summary.added;
                document.getElementById('s-deleted').innerText = data.summary.deleted;

                // 图表
                new Chart(document.getElementById('diffChart'), {{
                    type: 'doughnut',
                    data: {{
                        labels: ['差异', '新增', '删除', '相同'],
                        datasets: [{{
                            data: [data.summary.diff, data.summary.added, data.summary.deleted, data.summary.same],
                            backgroundColor: ['#fd7e14', '#007bff', '#dc3545', '#28a745']
                        }}]
                    }},
                    options: {{ responsive: true, maintainAspectRatio: false, plugins: {{ legend: {{ position: 'bottom' }} }} }}
                }});

                // 生成表格函数
                function createTable(items, type) {{
                    if (items.length === 0) return '<p style="text-align:center; color:#999; padding:20px;">无数据</p>';
                    
                    let html = `
                    <table>
                        <thead>
                            <tr>
                                <th class="col-path">文件路径</th>
                                <th class="col-status">状态</th>
                                <th class="col-sim">相似度</th>
                                <th class="col-size">A 大小</th>
                                <th class="col-size">B 大小</th>
                                <th class="col-size">增量 (Diff)</th>
                            </tr>
                        </thead>
                        <tbody>`;
                    
                    items.forEach(item => {{
                        let colorClass = '';
                        if(type === 'diff') colorClass = 'c-diff';
                        else if(type === 'added') colorClass = 'c-add';
                        else if(type === 'deleted') colorClass = 'c-del';
                        else colorClass = 'c-same';

                        // 格式化大小
                        const sizeA = item.size_a > 0 ? item.size_a.toLocaleString() + ' B' : '-';
                        const sizeB = item.size_b > 0 ? item.size_b.toLocaleString() + ' B' : '-';
                        let sizeDiff = item.size_diff > 0 ? '+' + item.size_diff : item.size_diff;
                        if(item.size_diff === 0) sizeDiff = '-';

                        html += `
                            <tr>
                                <td title="${{item.path}}">${{item.path}}</td>
                                <td class="${{colorClass}}"><b>${{item.status}}</b></td>
                                <td>${{item.similarity_str}}</td>
                                <td>${{sizeA}}</td>
                                <td>${{sizeB}}</td>
                                <td style="color:${{item.size_diff > 0 ? 'red' : (item.size_diff < 0 ? 'green' : 'black')}}">
                                    ${{sizeDiff}}
                                </td>
                            </tr>
                        `;
                    }});
                    html += '</tbody></table>';
                    return html;
                }}

                // 分类数据
                const diffItems = data.details.filter(i => i.type_category === 'diff');
                const addItems = data.details.filter(i => i.type_category === 'added');
                const delItems = data.details.filter(i => i.type_category === 'deleted');
                const sameItems = data.details.filter(i => i.type_category === 'same');

                document.getElementById('TabDiff').innerHTML = createTable(diffItems, 'diff');
                document.getElementById('TabAdd').innerHTML = createTable(addItems, 'added');
                document.getElementById('TabDel').innerHTML = createTable(delItems, 'deleted');
                document.getElementById('TabSame').innerHTML = createTable(sameItems, 'same');

                // Tab 切换逻辑
                window.openTab = function(evt, tabName) {{
                    var i, tabcontent, tablinks;
                    tabcontent = document.getElementsByClassName("tabcontent");
                    for (i = 0; i < tabcontent.length; i++) {{
                        tabcontent[i].style.display = "none";
                    }}
                    tablinks = document.getElementsByClassName("tablinks");
                    for (i = 0; i < tablinks.length; i++) {{
                        tablinks[i].className = tablinks[i].className.replace(" active", "");
                    }}
                    document.getElementById(tabName).style.display = "block";
                    evt.currentTarget.className += " active";
                }}
            </script>
        </body>
        </html>
        """
        try:
            with open(output_path, "w", encoding="utf-8") as f:
                f.write(html_content)
            return True
        except Exception as e:
            print(f"Export failed: {e}")
            return False

# --- GUI 界面部分 ---

class DiffApp:
    def __init__(self, root):
        self.root = root
        self.root.title("文件/安装包差异深度对比工具 (Pro)")
        self.root.geometry("1100x700")
        self.analyzer = FileAnalyzer()
        self.compare_result = None

        self._init_ui()

    def _init_ui(self):
        style = ttk.Style()
        style.configure("TButton", padding=5)
        
        # 顶部输入框
        input_frame = ttk.LabelFrame(self.root, text=" 对比配置 ", padding=10)
        input_frame.pack(fill="x", padx=10, pady=5)

        self._create_path_row(input_frame, "旧版本 (A):", "path_a", 0)
        self._create_path_row(input_frame, "新版本 (B):", "path_b", 1)

        # 按钮区
        btn_frame = ttk.Frame(input_frame)
        btn_frame.grid(row=2, column=0, columnspan=4, pady=10)
        
        self.btn_compare = ttk.Button(btn_frame, text="▶ 开始深度对比", command=self.start_comparison)
        self.btn_compare.pack(side="left", padx=10)
        
        self.btn_export = ttk.Button(btn_frame, text="📄 导出HTML报告", command=self.export_report, state="disabled")
        self.btn_export.pack(side="left", padx=10)

        self.lbl_info = ttk.Label(btn_frame, text="请选择文件开始...", foreground="#666")
        self.lbl_info.pack(side="left", padx=20)

        # 进度条
        self.progress = ttk.Progressbar(self.root, orient="horizontal", mode="indeterminate")

        # 结果列表
        tree_frame = ttk.LabelFrame(self.root, text=" 详细差异列表 (点击表头排序) ", padding=5)
        tree_frame.pack(fill="both", expand=True, padx=10, pady=5)

        cols = ("path", "status", "sim", "size_a", "size_b", "diff_val")
        self.tree = ttk.Treeview(tree_frame, columns=cols, show="headings")
        
        # 定义列属性
        self.tree.heading("path", text="文件路径", command=lambda: self.sort_tree("path", False))
        self.tree.heading("status", text="状态", command=lambda: self.sort_tree("status", False))
        self.tree.heading("sim", text="相似度", command=lambda: self.sort_tree("sim", False))
        self.tree.heading("size_a", text="Size A", command=lambda: self.sort_tree("size_a", False))
        self.tree.heading("size_b", text="Size B", command=lambda: self.sort_tree("size_b", False))
        self.tree.heading("diff_val", text="大小差异 (+/-)", command=lambda: self.sort_tree("diff_val", False))

        self.tree.column("path", width=450)
        self.tree.column("status", width=80, anchor="center")
        self.tree.column("sim", width=80, anchor="center")
        self.tree.column("size_a", width=90, anchor="e")
        self.tree.column("size_b", width=90, anchor="e")
        self.tree.column("diff_val", width=100, anchor="e")

        sb_v = ttk.Scrollbar(tree_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscroll=sb_v.set)
        self.tree.pack(side="left", fill="both", expand=True)
        sb_v.pack(side="right", fill="y")

        # 定义颜色Tag
        self.tree.tag_configure("diff", foreground="#d35400") # 橙
        self.tree.tag_configure("added", foreground="#0056b3") # 蓝
        self.tree.tag_configure("deleted", foreground="#c0392b") # 红
        self.tree.tag_configure("same", foreground="#27ae60") # 绿

    def _create_path_row(self, parent, label, var_name, row):
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="e", padx=5)
        var = tk.StringVar()
        setattr(self, var_name, var)
        ttk.Entry(parent, textvariable=var, width=70).grid(row=row, column=1, padx=5)
        ttk.Button(parent, text="文件", width=6, command=lambda: self.browse(var, 'file')).grid(row=row, column=2, padx=2)
        ttk.Button(parent, text="目录", width=6, command=lambda: self.browse(var, 'dir')).grid(row=row, column=3, padx=2)

    def browse(self, var, type_):
        if type_ == 'file':
            p = filedialog.askopenfilename(filetypes=[("Package", "*.zip *.apk *.ipa *.jar"), ("All", "*.*")])
        else:
            p = filedialog.askdirectory()
        if p: var.set(p)

    def start_comparison(self):
        pa, pb = self.path_a.get(), self.path_b.get()
        if not pa or not pb:
            messagebox.showwarning("提示", "请先选择两个路径")
            return
        
        self.btn_compare.config(state="disabled")
        self.tree.delete(*self.tree.get_children())
        self.progress.pack(fill="x", padx=10)
        self.progress.start(10)
        
        t = threading.Thread(target=self._run_thread, args=(pa, pb))
        t.daemon = True
        t.start()

    def _run_thread(self, pa, pb):
        try:
            res = self.analyzer.compare(pa, pb, lambda m: self.root.after(0, self.lbl_info.config, {"text": m}))
            self.root.after(0, self._on_finished, res)
        except Exception as e:
            self.root.after(0, messagebox.showerror, "Error", str(e))
            self.root.after(0, self._reset_ui)

    def _on_finished(self, result):
        self.compare_result = result
        self._reset_ui()
        self.btn_export.config(state="normal")
        
        summary = result['summary']
        self.lbl_info.config(text=f"分析完成! 总计: {summary['total']} | 差异: {summary['diff']} | 新增: {summary['added']} | 删除: {summary['deleted']}")

        # --- 优化开始：分批加载数据，防止卡死 ---
        
        # 1. 先清空表格
        self.tree.delete(*self.tree.get_children())
        
        # 2. 准备数据
        all_items = result["details"]
        total_items = len(all_items)
        batch_size = 50  # 每次加载 50 行
        
        # 3. 定义递归插入函数
        def insert_batch(start_index):
            end_index = min(start_index + batch_size, total_items)
            
            # 临时关闭屏幕更新以提高插入速度（可选，但对Treeview很有效）
            # self.tree.pack_forget() 
            
            for i in range(start_index, end_index):
                item = all_items[i]
                sa = f"{item['size_a']:,}" if item['size_a'] > 0 else "-"
                sb = f"{item['size_b']:,}" if item['size_b'] > 0 else "-"
                sd = f"{item['size_diff']:+,}" if item['size_diff'] != 0 else "-"
                
                self.tree.insert("", "end", values=(
                    item["path"], 
                    item["status"], 
                    item["similarity_str"], 
                    sa, 
                    sb, 
                    sd
                ), tags=(item["type_category"],))
            
            # self.tree.pack(side="left", fill="both", expand=True) # 如果上面隐藏了，这里要显示回来

            # 更新一下界面上的提示，让用户知道正在渲染
            self.lbl_info.config(text=f"正在渲染列表... {end_index}/{total_items}")

            if end_index < total_items:
                # 如果还没插完，10毫秒后继续插下一批
                self.root.after(10, insert_batch, end_index)
            else:
                # 全部插完，恢复最终状态提示
                self.lbl_info.config(text=f"就绪! 总计: {summary['total']} | 差异: {summary['diff']} | 新增: {summary['added']} | 删除: {summary['deleted']}")
        
        # 4. 启动第一批插入
        if total_items > 0:
            insert_batch(0)
        # --- 优化结束 ---

    def _reset_ui(self):
        self.progress.stop()
        self.progress.pack_forget()
        self.btn_compare.config(state="normal")

    def export_report(self):
        if not self.compare_result: return
        f = filedialog.asksaveasfilename(defaultextension=".html", filetypes=[("HTML", "*.html")], initialfile="diff_report.html")
        if f:
            if ReportGenerator.generate_html(self.compare_result, f):
                if messagebox.askyesno("成功", "报告已生成，打开查看？"):
                    webbrowser.open("file://" + os.path.abspath(f))

    # --- 增强的排序算法 ---
    def sort_tree(self, col, reverse):
        l = [(self.tree.set(k, col), k) for k in self.tree.get_children('')]
        
        def convert(val):
            # 处理字符串转数字用于排序
            s = val.replace(',', '').replace('%', '').replace('+', '')
            if s == '-': return -1 if 'size' in col or 'diff' in col else 0
            try:
                return float(s)
            except ValueError:
                return s.lower()

        l.sort(key=lambda t: convert(t[0]), reverse=reverse)

        for index, (_, k) in enumerate(l):
            self.tree.move(k, '', index)

        self.tree.heading(col, command=lambda: self.sort_tree(col, not reverse))

if __name__ == "__main__":
    root = tk.Tk()
    DiffApp(root)
    root.mainloop()