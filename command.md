=> Sử dụng khi muốn cập nhật lại knowledge base
$env:USE_QDRANT="true"
$env:QDRANT_HOST="localhost"

@'
from app.modules.knowledge_base import get_knowledge_base
kb = get_knowledge_base()
print("KB entries:", len(kb.entries))
'@ | python -


Chạy:

cd /mnt/d/Work/Learn/AI_X_Challenge

runId="qwen2_5_7b_lora_raft_smoke_a100"

source .venv-llama/bin/activate

python -m pip install -r external/llama.cpp/requirements/requirements-convert_hf_to_gguf.txt

python external/llama.cpp/convert_hf_to_gguf.py \
  "finetuning/runs/$runId/merged" \
  --outfile "finetuning/runs/$runId/physics-qwen-f16.gguf" \
  --outtype f16
Sau đó quantize:

cmake -S external/llama.cpp -B external/llama.cpp/build -DCMAKE_BUILD_TYPE=Release
cmake --build external/llama.cpp/build --config Release -j

external/llama.cpp/build/bin/llama-quantize \
  "finetuning/runs/$runId/physics-qwen-f16.gguf" \
  "finetuning/runs/$runId/physics-qwen-q4_k_m.gguf" \
  Q4_K_M
Kiểm tra:

ls -lh "finetuning/runs/$runId/"*.gguf

