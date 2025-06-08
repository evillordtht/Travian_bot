# --- travian_bot_project/bot/farming_manager.py ---
import time
import random
import logging
from typing import List, Dict, Optional, Any
from .travian_client import TravianClient
from .game_state import PlayerAccount, Village, Troop # PlayerAccount eklendi

logger = logging.getLogger(__name__)

class FarmingManager:
    """
    Otomatik yağma operasyonlarını yönetir. [cite: 249]
    Yağma hedeflerini işler, askerleri kontrol eder ve saldırıları gönderir. [cite: 249]
    """
    def __init__(self, client: TravianClient, account_data: PlayerAccount, gui_logger_callback=None):
        self.client = client
        self.account_data = account_data
        self.gui_logger_callback = gui_logger_callback
        self.farm_list: List[Dict[str, Any]] = [] # Başlangıçta boş, YZ veya kullanıcı dolduracak [cite: 249]
        self.raid_interval_seconds = 10 # Her bir yağma saldırısı arası minimum bekleme
        self.target_cooldown_seconds = 30 * 60 # Aynı hedefe tekrar saldırmadan önce 30 dk bekleme [cite: 252]

    def log_message(self, message: str):
        """Hem konsola hem de GUI'ye (varsa) log mesajı gönderir."""
        logger.info(message)
        if self.gui_logger_callback:
            self.gui_logger_callback(message)

    def set_farm_list(self, new_farm_list: List[Dict[str, Any]]):
        """Yağma listesini günceller. YZ'den gelen veya manuel eklenen listeyi alır."""
        # Basitçe üzerine yazmak yerine, YZ'den gelenleri mevcutlara ekleyebilir veya daha akıllı birleştirme yapılabilir.
        # Şimdilik, YZ'den gelen liste ana liste olsun.
        # Yinelenen koordinatları engellemek için bir kontrol eklenebilir.
        validated_targets = []
        seen_coords = set()

        for target in new_farm_list:
            if not isinstance(target.get("target_coords"), dict) or \
               not isinstance(target.get("troops"), dict):
                self.log_message(f"Geçersiz hedef formatı atlanıyor: {target}")
                continue

            coords = (target["target_coords"].get("x"), target["target_coords"].get("y"))
            if None in coords:
                self.log_message(f"Geçersiz koordinatlı hedef atlanıyor: {target}")
                continue

            if coords not in seen_coords:
                target.setdefault("last_raid_time", 0) # Eğer yoksa varsayılan ekle
                target.setdefault("source_village_id", self.account_data.villages[0].id if self.account_data.villages else None) # Varsayılan kaynak köy
                validated_targets.append(target)
                seen_coords.add(coords)
            else:
                self.log_message(f"Yinelenen hedef koordinatı ({coords}) atlanıyor.")


        self.farm_list = validated_targets
        self.log_message(f"Yağma listesi {len(self.farm_list)} hedefle güncellendi.")
        if self.gui_logger_callback and hasattr(self.gui_logger_callback.__self__, 'update_farm_targets_display'): # GUI'yi güncelle
            self.gui_logger_callback.__self__.update_farm_targets_display(self.farm_list)


    def automated_farming_cycle(self):
        """
        Yağma listesini döngüsel olarak kontrol eder ve saldırıları gönderir. [cite: 251]
        Her hedef için asker kontrolü ve bekleme süresi yönetimi yapar. [cite: 251]
        """
        if not self.account_data.villages:
            self.log_message("Hesapta aktif köy bulunmadığı için yağma yapılamıyor.")
            return

        if not self.farm_list:
            self.log_message("Yağma listesi boş. Yağma döngüsü atlanıyor.")
            return

        self.log_message(f"Otomatik yağma döngüsü başlatılıyor ({len(self.farm_list)} hedef)...")
        random.shuffle(self.farm_list) # Hedeflere rastgele sırada saldırmak için [cite: 252]

        for farm_target in self.farm_list:
            source_village_id = farm_target.get("source_village_id", self.account_data.villages[0].id) # YZ'den gelmezse ilk köy [cite: 252]
            target_coords = farm_target["target_coords"]
            troops_to_send_dict = farm_target["troops"] # {'Lejyoner': 10, 'Baltacı': 5} gibi

            # Kaynak köyü bul
            source_village: Optional[Village] = next((v for v in self.account_data.villages if v.id == source_village_id), None)

            if not source_village:
                self.log_message(f"Yağma için kaynak köy ID {source_village_id} bulunamadı. Hedef {target_coords} atlanıyor.")
                continue

            # Hedef bekleme süresi kontrolü
            last_raid_time = farm_target.get("last_raid_time", 0)
            if (time.time() - last_raid_time) < self.target_cooldown_seconds:
                remaining_cooldown = int((self.target_cooldown_seconds - (time.time() - last_raid_time)) / 60)
                self.log_message(f"Hedef {target_coords} (Köy: {farm_target.get('village_name', 'Bilinmiyor')}) beklemede. Kalan süre: ~{remaining_cooldown} dakika.")
                continue

            # Asker yeterlilik kontrolü
            can_send_raid = True
            actual_troops_to_send = {} # Yeterli asker varsa gönderilecek miktar
            missing_troops_log = []

            for troop_name, required_count_raw in troops_to_send_dict.items():
                try:
                    required_count = int(required_count_raw)
                    if required_count <= 0: continue # Geçerli olmayan miktarı atla
                except ValueError:
                    self.log_message(f"Hedef {target_coords} için '{troop_name}' asker miktarı ({required_count_raw}) geçersiz. Atlanıyor.")
                    can_send_raid = False
                    break # Bu hedefi tamamen atla

                found_at_home_count = 0
                for troop_at_home in source_village.troops_home: # BotEngine'in güncellediği troops_home kullanılır
                    if troop_at_home.type_name.lower() == troop_name.lower(): # İsimleri küçük harfe çevirerek karşılaştır
                        found_at_home_count = troop_at_home.count
                        break

                if found_at_home_count >= required_count:
                    actual_troops_to_send[troop_name] = required_count
                else:
                    missing_troops_log.append(f"{troop_name} (istenilen: {required_count}, mevcut: {found_at_home_count})")
                    can_send_raid = False # Eğer herhangi bir asker tipi yetersizse bu hedefi atla

            if not can_send_raid or not actual_troops_to_send: # Ya asker yetersiz ya da gönderilecek asker yok
                if missing_troops_log: # Sadece eksik varsa logla
                    self.log_message(f"Köy '{source_village.name}' -> {target_coords} (Ad: {farm_target.get('village_name')}) hedefine yeterli asker yok. Eksikler: {', '.join(missing_troops_log)}")
                elif not actual_troops_to_send and troops_to_send_dict : # İstenen asker var ama hepsi 0 veya geçersizdi
                    self.log_message(f"Köy '{source_village.name}' -> {target_coords} (Ad: {farm_target.get('village_name')}) hedefine gönderilecek geçerli asker bulunamadı.")
                continue


            self.log_message(f"Köy '{source_village.name}' adresinden {target_coords} (Ad: {farm_target.get('village_name')}) hedefine {actual_troops_to_send} ile yağma gönderiliyor...")

            if self.client.send_raid(source_village.id, target_coords, actual_troops_to_send):
                self.log_message(f"Yağma saldırısı {target_coords} (Ad: {farm_target.get('village_name')}) hedefine başarıyla gönderildi.")
                farm_target["last_raid_time"] = time.time() # Son yağma zamanını güncelle [cite: 253]
            else:
                self.log_message(f"Yağma saldırısı {target_coords} (Ad: {farm_target.get('village_name')}) hedefine gönderilemedi.")

            # Botun çok hızlı davranmasını engellemek için rastgele bir bekleme
            time.sleep(random.uniform(self.raid_interval_seconds, self.raid_interval_seconds + 10))

        self.log_message("Otomatik yağma döngüsü tamamlandı.")
