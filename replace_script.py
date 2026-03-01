import csv
import os
from pathlib import Path
import uuid

# ================= 配置区域 =================
SOURCE_DIR = Path('source')
RESULT_DIR = Path('results')
CSV_FILE = Path('mapping.csv')

# 编码尝试顺序 (根据实际文件编码调整，防止乱码)
ENCODINGS = ['utf-8', 'gbk', 'gb18030', 'utf-8-sig']

# 占位符前缀 (使用 UUID 确保唯一性，避免与原文冲突)
PLACEHOLDER_PREFIX = f"__REPLACE_{uuid.uuid4().hex[:8]}_"
# ===========================================

def load_mapping(csv_path):
    """
    读取 CSV 映射关系。
    返回：
    1. replace_rules: 列表 [(旧内容，新内容), ...] 用于文本替换
    2. rename_map: 字典 {旧文件名 stem: 新文件名 stem} 用于文件重命名
    """
    replace_rules = []
    rename_map = {}
    
    if not csv_path.exists():
        print(f"错误：未找到配置文件 {csv_path}")
        return replace_rules, rename_map
    
    try:
        # 读取 CSV，处理可能的 BOM 头
        with open(csv_path, 'r', encoding='utf-8-sig', newline='') as f:
            reader = csv.reader(f)
            for row in reader:
                if len(row) >= 2:
                    old_val = row[0].strip()
                    new_val = row[1].strip()
                    
                    if old_val:
                        # 1. 加入文本替换规则
                        replace_rules.append((old_val, new_val))
                        # 2. 加入文件名重命名映射 ( key: 旧 stem, value: 新 stem )
                        rename_map[old_val] = new_val
    except Exception as e:
        print(f"读取 CSV 失败：{e}")
        
    return replace_rules, rename_map

def read_file_content(file_path):
    """
    尝试多种编码读取文件内容，返回 (内容，使用的编码)
    """
    for enc in ENCODINGS:
        try:
            with open(file_path, 'r', encoding=enc) as f:
                return f.read(), enc
        except (UnicodeDecodeError, LookupError):
            continue
    # 如果都失败，强制 utf-8 忽略错误
    with open(file_path, 'rb') as f:
        return f.read().decode('utf-8', errors='ignore'), 'utf-8 (forced)'

def safe_replace_content(content, rules):
    """
    安全替换内容，使用占位符避免循环替换问题。
    
    三阶段替换：
    1. 将所有待替换内容 -> 唯一占位符 (记录替换类型)
    2. 将所有占位符 -> 最终目标值
    
    支持三种格式：
    1. 双引号 "xxx"
    2. 单引号 'xxx'
    3. 无引号、逗号结尾 xxx,
    """
    if not rules:
        return content, False
    
    # 占位符映射：{占位符：(新值，格式类型)}
    # 格式类型：'"' 双引号，"'" 单引号，',' 逗号结尾
    placeholders = {}
    modified = False
    
    # ========== 第一阶段：原文本 -> 占位符 ==========
    for idx, (old_val, new_val) in enumerate(rules):
        placeholder = f"{PLACEHOLDER_PREFIX}{idx}__"
        
        # 格式 1: 双引号 "xxx"
        search_str_double = f'"{old_val}"'
        if search_str_double in content:
            content = content.replace(search_str_double, placeholder)
            placeholders[placeholder] = (new_val, '"')
            modified = True
        
        # 格式 2: 单引号 'xxx'
        search_str_single = f"'{old_val}'"
        if search_str_single in content:
            content = content.replace(search_str_single, placeholder)
            placeholders[placeholder] = (new_val, "'")
            modified = True
        
        # 格式 3: 无引号、逗号结尾 xxx,
        search_str_comma = f'{old_val},'
        if search_str_comma in content:
            content = content.replace(search_str_comma, placeholder)
            placeholders[placeholder] = (new_val, ',')
            modified = True
    
    # ========== 第二阶段：占位符 -> 最终目标值 ==========
    for placeholder, (new_val, format_type) in placeholders.items():
        if format_type == ',':
            # 逗号结尾格式：新值 + 逗号
            replace_str = f'{new_val},'
        else:
            # 引号格式：引号 + 新值 + 引号
            replace_str = f'{format_type}{new_val}{format_type}'
        content = content.replace(placeholder, replace_str)
    
    return content, modified

def process_files(rules, rename_map):
    """
    主处理逻辑：内容替换 + 条件重命名
    """
    if not SOURCE_DIR.exists():
        print(f"错误：源文件夹 {SOURCE_DIR} 不存在。")
        return

    # 创建结果文件夹
    RESULT_DIR.mkdir(exist_ok=True)

    # 获取源文件夹下所有文件
    files = [f for f in SOURCE_DIR.iterdir() if f.is_file()]
    
    if not files:
        print(f"提示：{SOURCE_DIR} 文件夹下没有找到文件。")
        return

    print(f"开始处理 {len(files)} 个文件...")
    print(f"加载了 {len(rules)} 条替换规则，{len(rename_map)} 条重命名规则。")
    print("-" * 30)

    success_count = 0
    for file_path in files:
        file_stem = file_path.stem      # 去掉后缀的文件名
        file_suffix = file_path.suffix  # 后缀，例如 .txt
        file_name = file_path.name      # 完整文件名
        
        try:
            # 1. 确定新文件名
            # 如果文件名 stem 完全匹配 CSV 第一列，则使用 CSV 第二列作为新 stem
            new_stem = rename_map.get(file_stem, file_stem)
            new_filename = f"{new_stem}{file_suffix}"
            
            # 2. 读取内容
            content, used_encoding = read_file_content(file_path)
            
            # 3. 执行文本替换 (使用安全的占位符替换)
            content, modified = safe_replace_content(content, rules)
            
            # 4. 保存结果
            output_path = RESULT_DIR / new_filename
            
            # 检查结果文件夹中是否已存在同名文件（防止重命名冲突）
            if output_path.exists() and str(output_path) != str(file_path):
                print(f"[警告] 目标文件已存在，将被覆盖：{new_filename}")
            
            with open(output_path, 'w', encoding=used_encoding) as f:
                f.write(content)
            
            # 5. 打印日志
            status_content = "内容已改" if modified else "内容不变"
            status_name = "已重命名" if file_stem != new_stem else "名不变"
            print(f"[{status_content} | {status_name}] {file_name} -> {new_filename}")
            success_count += 1

        except Exception as e:
            print(f"[失败] {file_path.name}: {e}")
            import traceback
            traceback.print_exc()

    print("-" * 30)
    print(f"处理完成。成功处理：{success_count}/{len(files)}")
    print(f"结果已保存至：{RESULT_DIR.absolute()}")

if __name__ == '__main__':
    # 1. 加载映射规则
    rules, rename_map = load_mapping(CSV_FILE)
    
    if not rules:
        print("未加载到任何替换规则，程序退出。")
        print(f"请确保 {CSV_FILE} 存在且格式正确（第一列旧值，第二列新值）。")
    else:
        # 预览规则
        print(f"已加载 {len(rules)} 条规则。")
        print("规则预览 (旧 -> 新):")
        for i, (old, new) in enumerate(rules[:5]):
            print(f"  {i+1}. \"{old}\" -> \"{new}\" (文件名匹配：{old}.txt -> {new}.txt)")
        if len(rules) > 5:
            print(f"  ... 还有 {len(rules)-5} 条规则")
        
        print("-" * 30)
        # 2. 开始处理
        process_files(rules, rename_map)