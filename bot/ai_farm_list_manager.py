# --- travian_bot_project/bot/ai_farm_list_manager.py ---
import google.generativeai as genai
import logging
import json
import re
import time
from typing import Dict, Any, List, Optional
from config.gemini_config import load_gemini_api_key # Güncellenmiş import
from .game_state import Village, Troop # Village doğrudan kullanılmıyor ama Troop kullanılıyor

logger = logging.getLogger(__name__)

class AIFarmListManager:
    """
    Gemini API'sini kullanarak potansiyel yağma hedeflerini belirler. [cite: 255]
    """
    def __init__(self, gui_logger_callback=None):
        self.api_key = load_gemini_api_key()
        if not self.api_key:
            # gui_logger_callback çağrılmadan önce logger ile hata basılabilir.
            logger.critical("Gemini API anahtarı yüklenemedi. AI Farm List Manager başlatılamıyor.")
            # GUI logger varsa oraya da bilgi verelim.
            if gui_logger_callback:
                gui_logger_callback("HATA: Gemini API anahtarı yüklenemedi. .env dosyasını kontrol edin.")
            # API anahtarı olmadan bu sınıf işlevsiz olacağından, bir istisna fırlatmak daha uygun olabilir.
            # Ya da model'i None olarak ayarlayıp, her çağrıda kontrol edebiliriz.
            # raise ValueError("Gemini API anahtarı yüklenemedi.") # Bu programı durdurur
            self.model = None # API anahtarı yoksa model None olacak
        else:
            genai.configure(api_key=self.api_key)
            self.model = genai.GenerativeModel('gemini-pro')  # Model adını güncel tutun
        self.gui_logger_callback = gui_logger_callback
        self.last_ai_check_time = 0
        self.ai_cooldown_seconds = 15 * 60  # YZ'yi sorgulama arası 15 dakika bekleme [cite: 259]

    def log_message(self, message: str, level: str = "info"):
        """Hem konsola hem de GUI'ye (varsa) log mesajı gönderir.""" 
        if level == "error":
            logger.error(message)
        elif level == "warning":
            logger.warning(message)
        else:
            logger.info(message)

        if self.gui_logger_callback:
            self.gui_logger_callback(message)

    def generate_farm_list_prompt(self, nearby_villages_info: List[Dict[str, Any]], current_village_troops: List[Troop]) -> str:
        """
        Yakındaki köylerin/vahaların bilgileri ve mevcut askerlere göre bir YZ istemi oluşturur.
        YZ'den JSON formatında bir yağma listesi döndürmesini ister.
        """
        # YZ'ye gönderilecek köy/vaha bilgilerini basitleştir ve gereksiz detayları kaldır
        simplified_nearby_info = []
        for v_info in nearby_villages_info:
            simplified_info = {
                "name": v_info.get("name", "Bilinmeyen"),
                "coords": v_info.get("coords"),
                "population": v_info.get("population"),
                "type": v_info.get("type", "village"), # village, oasis_wood, oasis_crop vb.
                "player_status": v_info.get("player_status", "bilinmiyor"), # inaktif, aktif, vaha vb.
                "defense_hint": v_info.get("defense_hint", "bilinmiyor") # zayıf, bilinmiyor, natar vb.
            }
            simplified_nearby_info.append(simplified_info)


        prompt = (
            "Sen bir Travian strateji uzmanı yapay zekasın. Görevin, yağma için uygun hedefleri belirlemek.\n"
            "Sana JSON formatında yakındaki köylerin ve vahaların bir listesini ve mevcut askerlerimi vereceğim.\n"
            "Amacın: Bu listeden en verimli ve en az riskli yağma hedeflerini seçmek.\n"
            "Önceliklerin:\n"
            "1. Açıkça 'inaktif', 'terkedilmiş' veya 'çok zayıf savunmalı' olarak belirtilen köyler/vahalar.\n"
            "2. Düşük nüfuslu (örneğin <100) oyuncu köyleri (eğer aktif değilse).\n"
            "3. Natarlara ait olan veya savunmasız olduğu belirtilen vahalar.\n"
            "Dikkat Et: 'Aktif', 'çok aktif', 'güçlü ittifak', 'yüksek savunma' gibi ifadeler içeren hedeflerden KAÇIN.\n"
            "Çıktı Formatı: SADECE aşağıdaki gibi bir JSON listesi döndür. BAŞKA HİÇBİR METİN EKLEME (açıklama, selamlama vb. YOK).\n"
            "Örnek JSON Çıktısı:\n"
            "[\n"
            "  {\"village_name\": \"Terkedilmiş Vadi\", \"target_coords\": {\"x\": 10, \"y\": -5}, \"troops\": {\"Lejyoner\": 20, \"Baltacı\": 15}},\n"
            "  {\"village_name\": \"Issız Odunluk (Vaha)\", \"target_coords\": {\"x\": 25, \"y\": 12}, \"troops\": {\"Falanks\": 30}}\n"
            "]\n"
            "Asker Önerileri: Her hedef için, göndermeyi önerdiğin asker tiplerini ve MİKTARLARINI belirt. Mevcut askerlerimi dikkate al. Mümkünse farklı asker tipleri kullan.\n"
            "Mevcut Askerlerim:\n"
            + (", ".join([f"- {t.type_name}: {t.count}" for t in current_village_troops]) if current_village_troops else "Hiç askerim yok.") + "\n"
            "Yakındaki Köyler/Vahalar (JSON formatında liste):\n"
            + json.dumps(simplified_nearby_info, indent=2, ensure_ascii=False) + "\n"
            "Lütfen sadece yukarıdaki formata uygun bir JSON listesi döndür."
        )
        return prompt

    def suggest_farm_targets(self, nearby_villages_info: List[Dict[str, Any]], current_village_troops: List[Troop]) -> List[Dict[str, Any]]:
        """Gemini AI'dan yağma hedefi önerileri alır."""
        if not self.model:
            self.log_message("HATA: Gemini modeli yüklenemedi (API anahtarı eksik olabilir). Yağma hedefi önerilemiyor.", level="error")
            return []

        if (time.time() - self.last_ai_check_time) < self.ai_cooldown_seconds:
            remaining_wait = int((self.ai_cooldown_seconds - (time.time() - self.last_ai_check_time)) / 60)
            self.log_message(f"YZ yağma hedefi önerisi için beklemede. Kalan süre: ~{remaining_wait} dakika.")
            return []

        if not nearby_villages_info:
            self.log_message("YZ'ye sunulacak yakındaki köy/vaha bilgisi bulunamadı. Öneri alınamıyor.", level="warning")
            return []

        prompt = self.generate_farm_list_prompt(nearby_villages_info, current_village_troops)
        self.log_message("YZ'ye yağma hedefi istemi gönderiliyor...")
        # self.log_message(f"Gönderilen Prompt (ilk 500 karakter):\n{prompt[:500]}...") # Debug için

        try:
            # Gemini API çağrısı için güvenlik ayarları ve generation_config
            safety_settings = [
                {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
                {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
                {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
                {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"},
            ]
            generation_config = genai.types.GenerationConfig(
                # candidate_count=1, # Tek bir yanıt yeterli
                # stop_sequences=['\n\n'], # Yanıtı nerede durduracağını belirtebilir
                max_output_tokens=2048, # Çıktı token limitini ayarla (JSON uzun olabilir)
                temperature=0.5, # Daha tutarlı yanıtlar için düşük sıcaklık
                # top_p=0.9,
                # top_k=40
            )

            response = self.model.generate_content(
                prompt,
                generation_config=generation_config,
                safety_settings=safety_settings
            )

            if not response.candidates or not response.candidates[0].content.parts:
                self.log_message("YZ'den geçerli bir yanıt alınamadı (aday veya içerik kısmı eksik).", level="warning")
                if response.prompt_feedback:
                     self.log_message(f"YZ Prompt Geri Bildirimi: {response.prompt_feedback}", level="warning")
                return []

            raw_response_text = response.text
            self.log_message(f"YZ'den yağma önerisi yanıtı alındı (ilk 300 karakter): {raw_response_text[:300]}...")

            # Yanıttan JSON bloğunu ayıkla (bazen Markdown formatında ```json ... ``` şeklinde gelebilir)
            json_match = re.search(r'```json\s*([\s\S]*?)\s*```', raw_response_text, re.DOTALL)
            if json_match:
                json_str = json_match.group(1)
            else: # Direkt JSON döndüğünü varsay
                json_str = raw_response_text.strip()


            try:
                farm_targets = json.loads(json_str)
                if not isinstance(farm_targets, list): # Dönen şeyin bir liste olduğundan emin ol [cite: 260]
                    self.log_message(f"YZ yanıtı beklenen JSON listesi formatında değil. Alınan: {type(farm_targets)}", level="error")
                    raise ValueError("YZ yanıtı JSON listesi değil.")

                # Gelen verinin beklenen alanları içerdiğinden emin ol
                validated_targets = []
                for target in farm_targets:
                    if isinstance(target, dict) and \
                       'target_coords' in target and isinstance(target['target_coords'], dict) and \
                       'x' in target['target_coords'] and 'y' in target['target_coords'] and \
                       'troops' in target and isinstance(target['troops'], dict):
                        target.setdefault("village_name", target.get("name", "YZ Hedefi")) # İsim yoksa varsayılan ata
                        validated_targets.append(target)
                    else:
                        self.log_message(f"YZ'den gelen hedef formatı yanlış veya eksik: {target}", level="warning")

                self.log_message(f"YZ'den {len(validated_targets)} adet geçerli yağma hedefi önerisi işlendi.")
                self.last_ai_check_time = time.time() # Başarılı çağrı sonrası zamanı güncelle [cite: 261]
                return validated_targets
            except json.JSONDecodeError as e:
                self.log_message(f"YZ yanıtı JSON olarak ayrıştırılamadı: {e}. Ham yanıt parçası: '{json_str[:200]}...'", level="error")
                return []
            except ValueError as ve: # Kendi eklediğimiz ValueError için
                self.log_message(str(ve), level="error")
                return []

        except Exception as e:
            self.log_message(f"Gemini API yağma hedefi çağrısı sırasında genel bir hata oluştu: {e}", level="error", exc_info=True)
            return []
