# --- travian_bot_project/config/gemini_config.py ---
import os
from dotenv import load_dotenv
import logging

logger = logging.getLogger(__name__)

def load_gemini_api_key():
    """Ortam değişkenlerinden veya .env dosyasından Gemini API anahtarını yükler."""
    load_dotenv()
    gemini_api_key = os.getenv("GEMINI_API_KEY")
    if not gemini_api_key:
        logger.error("Hata: GEMINI_API_KEY .env dosyasında veya ortam değişkenlerinde eksik.")
        return None
    logger.info("Gemini API Anahtarı başarıyla yüklendi.")
    return gemini_api_key

if __name__ == "__main__":
    # Test için basit bir günlükleme yapılandırması
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    key = load_gemini_api_key()
    if key:
        # Anahtarın tamamını loglamamak iyi bir pratiktir.
        logger.info(f"Test: Gemini API Anahtarı yüklendi (ilk 5 karakter): {key[:5]}...")
    else:
        logger.info("Test: Gemini API anahtarı yüklenemedi.")