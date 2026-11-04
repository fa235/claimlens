# ClaimLens — YOLOv8 Fine-tuning Pipeline

Fine-tunes YOLOv8 on the [CarDD dataset](https://cardd-ustc.github.io) to detect
6 types of car damage: **dent, scratch, crack, glass shatter, lamp broken, tire flat**.

> **Current status (interim):** Until this pipeline is run (blocked on CarDD
> data prep + SageMaker GPU quota), the backend uses a pretrained Hugging Face
> model — [`Naiscorp/car-damage-detection`](https://huggingface.co/Naiscorp/car-damage-detection)
> — via `DAMAGE_DETECTOR=huggingface` in `backend/.env`.
>
> Once we train our own YOLOv8 here and run `export_weights.py` /
> `export_from_s3.py`, switch the backend to `DAMAGE_DETECTOR=yolo` with
> `YOLO_WEIGHTS=weights/damage_detector.pt`. No other code changes needed —
> both backends return the same damage schema.

---

## Folder structure

```
training/
├── configs/
│   ├── dataset.yaml          ← YOLOv8 dataset config
│   └── train.yaml            ← default hyperparameters
├── data/
│   ├── raw/                  ← downloaded CarDD images + annotations (gitignored)
│   └── processed/            ← YOLOv8-format images + labels (gitignored)
├── runs/                     ← training outputs, checkpoints, plots (gitignored)
├── sagemaker/                ← AWS SageMaker training pipeline
│   ├── SETUP.md              ← one-time AWS setup guide
│   ├── .env.example          ← copy to .env and fill in AWS config
│   ├── iam_policy.json       ← IAM policy for SageMaker role
│   ├── train_entry.py        ← entry point script (runs inside SageMaker container)
│   ├── launch_training.py    ← kicks off SageMaker job from your laptop
│   ├── upload_data.py        ← uploads CarDD to S3 before training
│   ├── export_from_s3.py     ← downloads best.pt from S3 to backend after training
│   └── requirements_launcher.txt
├── scripts/
│   ├── download_cardd.py     ← Step 1: download dataset from Hugging Face
│   ├── prepare_dataset.py    ← Step 2: convert COCO → YOLOv8 format
│   ├── evaluate.py           ← Step 4: evaluate on test set
│   └── export_weights.py     ← deploy weights to backend (local training only)
└── requirements.txt
```

---

## Setup

```bash
cd training

# Create a virtual environment
python3 -m venv venv
source venv/bin/activate      # Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

---

## Training options

| Where | When to use | Script |
|---|---|---|
| **AWS SageMaker** ← recommended | Production, any time | `sagemaker/launch_training.py` |
| Local machine | Quick experiments only | `scripts/train.py` |

---

## SageMaker workflow (recommended)

### Prerequisites — one-time AWS setup
Follow `sagemaker/SETUP.md` to create your S3 bucket and IAM role (~15 min).

```bash
pip install -r sagemaker/requirements_launcher.txt
cp sagemaker/.env.example sagemaker/.env
# edit sagemaker/.env with your AWS config
```

### SM Step 1 — Download + prepare dataset (local)

```bash
pip install -r requirements.txt
python scripts/download_cardd.py
python scripts/prepare_dataset.py
```

### SM Step 2 — Upload data to S3

```bash
python sagemaker/upload_data.py
# Uploads data/processed/ → s3://your-bucket/claimlens/training-data/
```

### SM Step 3 — Launch training job

```bash
python sagemaker/launch_training.py
# Submits job, streams logs to terminal
# Takes ~1 hr on ml.g4dn.xlarge (~$0.74)
```

### SM Step 4 — Download weights + deploy to backend

```bash
python sagemaker/export_from_s3.py --job-name claimlens-yolov8-YYYYMMDD-HHMMSS
# Downloads best.pt from S3 → backend/weights/damage_detector.pt
# Updates YOLO_WEIGHTS in backend/.env automatically
```

### SM Step 5 — Restart backend

```bash
docker-compose restart backend
```

---

## Local training workflow (alternative)

### Step 1 — Download CarDD

```bash
python scripts/download_cardd.py
```

Downloads ~4,000 images (train/val/test) from Hugging Face into `data/raw/`.

If the dataset requires a Hugging Face account:
```bash
python scripts/download_cardd.py --hf-token hf_your_token_here
# or: export HF_TOKEN=hf_your_token_here
```

---

### Step 2 — Prepare dataset

```bash
python scripts/prepare_dataset.py
```

Converts COCO-format annotations to YOLOv8 format and writes:
- `data/processed/images/{train,val,test}/`
- `data/processed/labels/{train,val,test}/`
- `data/processed/dataset.yaml`

---

### Step 3 — Fine-tune

```bash
# Auto-detects your hardware and sets sensible defaults
python scripts/train.py

# Override specific options
python scripts/train.py --model yolov8m.pt --epochs 100 --batch 16

# Resume an interrupted run
python scripts/train.py --resume runs/train/cardd_yolov8s/weights/last.pt
```

**Hardware recommendations:**

| Hardware       | Model      | Epochs | Batch | ETA       |
|----------------|------------|--------|-------|-----------|
| Mac M1/M2 MPS  | yolov8s.pt | 50     | 8     | ~3–5 hrs  |
| Single GPU     | yolov8m.pt | 100    | 16    | ~2–4 hrs  |
| CPU only       | yolov8n.pt | 30     | 4     | ~8+ hrs   |

Outputs are saved to `runs/train/<run_name>/`:
- `weights/best.pt`  — best checkpoint by mAP50
- `weights/last.pt`  — final checkpoint
- `results.csv`      — per-epoch metrics
- `confusion_matrix.png`, `PR_curve.png`, etc.

---

### Step 4 — Evaluate

```bash
python scripts/evaluate.py --weights runs/train/cardd_yolov8s/weights/best.pt

# With visualisations (saves annotated prediction images)
python scripts/evaluate.py --weights best.pt --visualise --num-images 30
```

Target metrics on CarDD test set:
- mAP50 > 0.50 = acceptable
- mAP50 > 0.65 = strong

---

### Step 5 — Deploy to backend

```bash
python scripts/export_weights.py --weights runs/train/cardd_yolov8s/weights/best.pt
```

This:
1. Copies `best.pt` → `backend/weights/damage_detector.pt`
2. Updates `YOLO_WEIGHTS=weights/damage_detector.pt` in `backend/.env`
3. Saves a `manifest.json` with eval metrics for traceability

Then restart the backend:
```bash
# Docker
docker-compose restart backend

# Local
uvicorn app.main:app --reload
```

---

## Retraining with new data

Every claim stored in the PostgreSQL `claims` table has a `corrected_data`
field for human-reviewed corrections. To use that data for retraining:

1. Export reviewed claims from the DB
2. Add corrected images + labels to `data/raw/`
3. Re-run `prepare_dataset.py` and `train.py --resume last.pt`
4. Re-run `evaluate.py` and `export_weights.py`

This is the continuous fine-tuning loop — the more claims processed, the
better the model gets.

---

## Citation

```bibtex
@ARTICLE{CarDD,
  author  = {Wang, Xinkuang and Li, Wenjing and Wu, Zhongcheng},
  journal = {IEEE Transactions on Intelligent Transportation Systems},
  title   = {CarDD: A New Dataset for Vision-Based Car Damage Detection},
  year    = {2023},
  volume  = {24},
  number  = {7},
  pages   = {7202--7214},
  doi     = {10.1109/TITS.2023.3258480}
}
```
