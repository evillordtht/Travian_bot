# --- travian_bot_project/main.py ---
import customtkinter as ctk
from gui.app_window import TravianBotApp
import logging
import os
import sys # sys.stdout için

# Günlükleme Yapılandırması
def setup_logging():
    """Uygulama için merkezi günlükleme yapılandırmasını ayarlar."""
    logs_dir = "logs"
    if not os.path.exists(logs_dir):
        try:
            os.makedirs(logs_dir)
        except OSError as e:
            print(f"HATA: Log dizini ({logs_dir}) oluşturulamadı: {e}")
            # Log dizini oluşturulamazsa, sadece konsola loglama yapılabilir.
            # Veya program sonlandırılabilir. Şimdilik devam edelim.


    log_file_path = os.path.join(logs_dir, "bot.log")

    # Temel günlükleyiciyi ayarla
    # Birden fazla handler eklemek için basicConfig yerine addHandler kullanmak daha esnektir.
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO) # Tüm loglayıcılar için varsayılan seviye

    # Formatlayıcı
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(module)s.%(funcName)s:%(lineno)d - %(message)s')

    # Dosya Handler'ı (her zaman ekle)
    try:
        file_handler = logging.FileHandler(log_file_path, mode='a', encoding='utf-8') # 'a' append modu [cite: 293]
        file_handler.setFormatter(formatter)
        root_logger.addHandler(file_handler)
    except Exception as e:
        print(f"HATA: Dosya günlükleyicisi ({log_file_path}) ayarlanamadı: {e}")


    # Konsol (Stream) Handler'ı (stdout'a yönlendir)
    # sys.stdout bazen GUI uygulamalarında veya belirli ortamlarda None olabilir.
    if sys.stdout:
        console_handler = logging.StreamHandler(sys.stdout) # Konsola yaz 
        console_handler.setFormatter(formatter)
        console_handler.setLevel(logging.INFO) # Konsol için log seviyesi ayarlanabilir (örn: DEBUG)
        root_logger.addHandler(console_handler)
    else:
        print("UYARI: sys.stdout mevcut değil, konsol günlüklemesi devre dışı.")


    # Belirli modüller için log seviyelerini ayrıca ayarlayabilirsiniz:
    # logging.getLogger("playwright").setLevel(logging.WARNING) # Playwright loglarını azaltmak için

    # Test log mesajı
    logging.info("Günlükleme sistemi başarıyla yapılandırıldı.")


def main():
    setup_logging() # Önce günlüklemeyi ayarla
    logger = logging.getLogger(__name__) # main.py için logger al
    logger.info("Travian Bot Uygulaması başlatılıyor...")

    try:
        app = TravianBotApp()
        # Pencere kapatma olayını yakala ve botu/kaynakları düzgünce kapat
        app.protocol("WM_DELETE_WINDOW", app.on_closing)
        app.mainloop()
    except Exception as e:
        logger.critical("Uygulama başlatılırken veya çalışırken kritik bir hata oluştu!", exc_info=True)
    finally:
        logger.info("Travian Bot Uygulaması kapatıldı.") 
        logging.shutdown() # Tüm günlükleyicileri temizle


if __name__ == "__main__":
    main()
