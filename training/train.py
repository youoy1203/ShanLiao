import os
import torch
from datasets import load_dataset
from trl import SFTTrainer
from transformers import TrainingArguments
from unsloth import FastLanguageModel

# ================= 參數設定 =================
MAX_SEQ_LENGTH = 512
MODEL_NAME = "unsloth/Qwen2.5-1.5B-Instruct-bnb-4bit" # 預設使用 Qwen2.5 1.5B，可根據需要更換為 Qwen3 (若 Unsloth 支援)
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

def format_prompts(examples):
    # examples["conversations"] 包含 ShareGPT 格式資料
    conversations = examples["conversations"]
    texts = [tokenizer.apply_chat_template(convo, tokenize=False, add_generation_prompt=False) for convo in conversations]
    return { "text" : texts }

print("正在載入資料集...")
if not os.path.exists(TRAIN_FILE):
    raise FileNotFoundError(f"找不到訓練集檔案 {TRAIN_FILE}，請先執行 prepare_dataset.py")

dataset = load_dataset("json", data_files={"train": TRAIN_FILE, "eval": EVAL_FILE})
dataset = dataset.map(format_prompts, batched=True)

# ================= 4. 設定訓練超參數 =================
training_args = TrainingArguments(
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
    evaluation_strategy = "steps",
    eval_steps = 100,                  # 調整為每 100 步評估一次
    save_strategy = "steps",
    save_steps = 200,                  # 調整為每 200 步存檔一次
    report_to = "none",                # 停用 wandb 等第三方回報
)

# ================= 5. 開始訓練 =================
print("開始進行 SFT (Supervised Fine-Tuning) 微調...")
trainer = SFTTrainer(
    model = model,
    tokenizer = tokenizer,
    train_dataset = dataset["train"],
    eval_dataset = dataset["eval"],
    dataset_text_field = "text",
    max_seq_length = MAX_SEQ_LENGTH,
    dataset_num_proc = 2,
    packing = False,                   # 對於短句，packing 設為 False 較好
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
