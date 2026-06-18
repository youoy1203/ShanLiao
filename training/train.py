import os
import sys

# 自訂自動 flush 的 Writer 包裝類別，保證日誌在非 tty 環境下能即時寫入
class UnbufferedWriter:
    def __init__(self, stream):
        self.stream = stream
    def write(self, data):
        self.stream.write(data)
        self.stream.flush()
    def writelines(self, datas):
        self.stream.writelines(datas)
        self.stream.flush()
    def __getattr__(self, attr):
        return getattr(self.stream, attr)

# 重新導向 stdout/stderr 至專案根目錄的 training.log
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.abspath(os.path.join(CURRENT_DIR, ".."))
log_file = open(os.path.join(PROJECT_DIR, "training.log"), "w", encoding="utf-8")
sys.stdout = UnbufferedWriter(log_file)
sys.stderr = sys.stdout
print("重導向初始化成功！開始載入深度學習庫...")

import torch
import uuid
import datasets.fingerprint
import datasets.arrow_dataset

# 猴子補丁：繞過 Python 3.14 下 HuggingFace datasets 的 dill/pickle 序列化崩潰 Bug
def dummy_generate_fingerprint(*args, **kwargs):
    return uuid.uuid4().hex

datasets.fingerprint.generate_fingerprint = dummy_generate_fingerprint
datasets.arrow_dataset.generate_fingerprint = dummy_generate_fingerprint

# 猴子補丁：強制禁用 Dataset.map 的多進程，防止 TRL 內部多進程序列化 ConfigModuleInstance 崩潰
original_map = datasets.arrow_dataset.Dataset.map
def safe_map(self, *args, **kwargs):
    kwargs["num_proc"] = None
    return original_map(self, *args, **kwargs)
datasets.arrow_dataset.Dataset.map = safe_map

from trl import SFTTrainer, SFTConfig
from unsloth import FastLanguageModel

# ================= 參數設定 =================
MAX_SEQ_LENGTH = 512
MODEL_NAME = "unsloth/Qwen3-1.7B-unsloth-bnb-4bit" # Unsloth 官方 Qwen3 1.7B 4-bit 量化模型
# 基於目前檔案路徑動態取得專案根目錄，防範執行路徑不同帶來的問題
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.abspath(os.path.join(CURRENT_DIR, ".."))
DATA_DIR = os.path.join(PROJECT_DIR, "data")
TRAIN_FILE = os.path.join(DATA_DIR, "train.json")
EVAL_FILE = os.path.join(DATA_DIR, "eval.json")
OUTPUT_DIR = os.path.join(PROJECT_DIR, "outputs")
LORA_OUTPUT_DIR = os.path.join(OUTPUT_DIR, "lora_adapter")
GGUF_OUTPUT_DIR = os.path.join(OUTPUT_DIR, "gguf_model")

# ================= 1. 載入模型與分詞器 =================
# 限制該 PyTorch 進程最多僅能使用 70% 的 GPU 顯存 (預留顯存給宿主機其他應用)
torch.cuda.set_per_process_memory_fraction(0.7, 0)
print("已設定 GPU 顯存上限為 70% (約 11.4 GB)")
print("正在載入 4-bit 量化基座模型...")
model, tokenizer = FastLanguageModel.from_pretrained(
    model_name = MODEL_NAME,
    max_seq_length = MAX_SEQ_LENGTH,
    dtype = None,           # 自動檢測，若支援 bfloat16 會自動使用
    load_in_4bit = True,    # 4-bit 量化以節省 VRAM
)

# ================= 2. 設定 LoRA 參數 =================
print("正在設定 LoRA config...")
model = FastLanguageModel.get_peft_model(
    model,
    r = 16,                 # LoRA rank
    target_modules = ["q_proj", "k_proj", "v_proj", "o_proj",
                      "gate_proj", "up_proj", "down_proj"],
    lora_alpha = 16,
    lora_dropout = 0,       # 0 適合 Unsloth 加速
    bias = "none",
    use_gradient_checkpointing = "unsloth", # 節省 VRAM
    random_state = 3407,
    use_rslora = False,
    loftq_config = None,
)

# ================= 3. 準備 ChatML 模板與資料集 =================
# 設定 ChatML 格式的對話模板
from unsloth.chat_templates import get_chat_template

tokenizer = get_chat_template(
    tokenizer,
    chat_template = "chatml", # Qwen 與 Unsloth 推薦的格式
    mapping = {
        "role" : "role",
        "content" : "content",
        "user" : "user",
        "assistant" : "assistant",
        "system" : "system"
    },
)

# 新增特殊 token 以應付新版 TRL 的 vocab 檢驗，防止 ValueError
tokenizer.add_tokens(["<EOS_TOKEN>", "<PAD_TOKEN>"])
tokenizer.eos_token = "<EOS_TOKEN>"
tokenizer.pad_token = "<PAD_TOKEN>"

import json
from datasets import Dataset

print("正在載入資料集...")
if not os.path.exists(TRAIN_FILE):
    raise FileNotFoundError(f"找不到訓練集檔案 {TRAIN_FILE}，請先執行 prepare_dataset.py")

with open(TRAIN_FILE, "r", encoding="utf-8") as f:
    raw_data = json.load(f)

print("正在套用 ChatML 對話模板...")
texts = [tokenizer.apply_chat_template(item["conversations"], tokenize=False, add_generation_prompt=False) for item in raw_data]

# 繞過 Hugging Face 的 load_dataset builder 序列化，直接從記憶體建立 Dataset 物件，解決 Python 3.14 的 dill/pickle 崩潰問題
dataset = Dataset.from_dict({"text": texts})

# ================= 4. 設定訓練超參數 =================
training_args = SFTConfig(
    per_device_train_batch_size = 4,   # 提升為 4 (充分利用 16GB 顯存)
    gradient_accumulation_steps = 2,   # 等效 batch size = 8 (4 * 2)
    warmup_steps = 10,
    max_steps = -1,                    # 使用 epochs 模式而不是 steps 模式
    num_train_epochs = 2,              # 7000 筆資料建議 2 個 epoch 即可學會風格，防過擬合
    learning_rate = 2e-4,
    fp16 = not torch.cuda.is_bf16_supported(),
    bf16 = torch.cuda.is_bf16_supported(),
    logging_steps = 10,
    optim = "adamw_8bit",
    weight_decay = 0.01,
    lr_scheduler_type = "linear",
    seed = 3407,
    output_dir = OUTPUT_DIR,
    save_strategy = "steps",
    save_steps = 200,                  # 調整為每 200 步存檔一次
    report_to = "none",                # 停用 wandb 等第三方回報
    max_length = MAX_SEQ_LENGTH,       # 修正為新版 SFTConfig 的 max_length
    dataset_num_proc = 1,              # 強制單進程，防止 datasets 庫在多進程序列化時因 ConfigModuleInstance 崩潰
    packing = False,                   # 對於短句，packing 設為 False 較好，移入 SFTConfig
    eos_token = "<|im_end|>",          # 強制指定 Qwen/ChatML 的結束 token，防 TRL 檢查報錯
    pad_token = "<|endoftext|>",        # 強制指定 Qwen 的 pad token，防 TRL 檢查報錯
    use_liger_kernel = True,           # 啟用 Liger Kernel 優化，避開新版 TRL 對 logits 存取產生的相容性崩潰 Bug
)

# ================= 5. 開始訓練 =================
print("開始進行 SFT (Supervised Fine-Tuning) 微調...")
trainer = SFTTrainer(
    model = model,
    processing_class = tokenizer,
    train_dataset = dataset,
    args = training_args,
)

trainer_stats = trainer.train()
print(f"訓練結束！總耗時: {trainer_stats.metrics['train_runtime']:.2f} 秒。")

# ================= 6. 儲存 LoRA Adapter =================
print(f"正在儲存 LoRA adapter 至 {LORA_OUTPUT_DIR}...")
model.save_pretrained(LORA_OUTPUT_DIR)
tokenizer.save_pretrained(LORA_OUTPUT_DIR)

# ================= 7. 匯出合併的 GGUF 格式 (可供 Ollama 直接載入) =================
# 這一步會在訓練後，直接將基座模型和 LoRA 合併，並轉換為 GGUF 格式
print("正在將微調後的模型合併並轉換為 GGUF (Q4_K_M) 格式...")
# unsloth 內建的高效 GGUF 匯出
model.save_pretrained_gguf(
    GGUF_OUTPUT_DIR,
    tokenizer,
    quantization_method = "q4_k_m"      # 適合 Ollama 的 4-bit 量化
)

print("=" * 50)
print("微調完成！您可以直接在 WSL2 中使用以下指令將模型載入至 Ollama：")
print(f"ollama create shanliao-qwen -f {GGUF_OUTPUT_DIR}/Modelfile")
print("=" * 50)
