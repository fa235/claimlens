import os, sys, asyncio, json
os.environ['DATABASE_URL'] = 'sqlite:///./test_e2e.db'
sys.path.insert(0, '.')

from app.services.analyzer import analyze_image
from app.core.config import settings


async def main():
    img_path = sys.argv[1] if len(sys.argv) > 1 else "test_images/input_car_1.jpg"
    print(f"Provider: {settings.llm_provider}")
    print(f"Vision model: {settings.openai_vision_model}")
    print(f"Cost model: {settings.openai_cost_model}")
    print(f"Review threshold: {settings.review_confidence_threshold}\n")

    with open(img_path, "rb") as f:
        image_bytes = f.read()
    ext = os.path.splitext(img_path)[1].lower()
    media = "image/png" if ext == ".png" else "image/jpeg"
    print(f"Loaded image: {img_path} ({len(image_bytes)} bytes, {media})\n")

    print("Running LLM-only pipeline (vision + cost)...\n")
    result = await analyze_image(image_bytes, media)

    print("=== RESULT ===")
    print(json.dumps(result, indent=2))


asyncio.run(main())
