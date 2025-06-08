# --- travian_bot_project/bot/bot_engine.py ---
import time
import random
import logging
from typing import List, Dict, Optional, Any

# Corrected import: Ensure TravianClient is imported before BotEngine class definition
from .travian_client import TravianClient
from .game_state import PlayerAccount, Village, Building, Troop, HeroStatus # PlayerAccount kullanılacak
from .farming_manager import FarmingManager
from .ai_farm_list_manager import AIFarmListManager
from playwright.sync_api import Error as PlaywrightError # For catching Playwright specific errors

logger = logging.getLogger(__name__)

# Örnek yapılandırmalar (Normalde GUI'den, config dosyasından veya YZ'den gelebilir)
DEFAULT_BUILD_QUEUE_VILLAGE1 = [
    {"name": "Oduncu", "target_level": 2, "gid": "1", "location_id": "1"},
    {"name": "Tarla", "target_level": 2, "gid": "4", "location_id": "5"},
    {"name": "Tuğla Ocağı", "target_level": 1, "gid": "2", "location_id": "2"},
    {"name": "Demir Madeni", "target_level": 1, "gid": "3", "location_id": "3"},
    {"name": "Merkez Binası", "target_level": 3, "gid": "15", "location_id": "26"}, # Konum ID'leri değişebilir
    {"name": "Tahıl Ambarı", "target_level": 2, "gid": "11", "location_id": "22"},
    {"name": "Depo", "target_level": 2, "gid": "10", "location_id": "21"},
    {"name": "Kışla", "target_level": 1, "gid": "19", "location_id": "30"},
]

DEFAULT_TROOP_TRAINING_PREFS = {
    "Lejyoner": {"min_count": 10, "train_amount": 5, "building_gid": "19"},
}


class BotEngine:
    """
    Botun "beynidir". Temel karar verme algoritmalarını, görev zamanlama mantığını
    ve çeşitli otomasyon stratejilerinin (inşaat, asker eğitimi, yağma, macera)
    uygulamalarını barındırır.
    """
    def __init__(self, client: TravianClient, account_data: PlayerAccount, gui_logger_callback=None):
        self.client = client # Client is passed in, but not yet logged in by this thread
        self.account_data = account_data # Artık PlayerAccount tipinde
        self.is_running = False
        self.gui_logger_callback = gui_logger_callback
        self.next_adventure_check_time = 0
        self.adventure_cooldown_initial = random.uniform(5*60, 10*60)
        self.adventure_cooldown_success = random.uniform(60*60, 120*60)
        self.adventure_cooldown_fail = random.uniform(10*60, 20*60)

        self.farming_manager = FarmingManager(client, account_data, self.log_message_wrapper)
        self.ai_farm_list_manager = AIFarmListManager(self.log_message_wrapper)
        self.next_farm_list_ai_update_time = time.time() # İlk YZ güncellemesi hemen denenebilir
        self.ai_farm_update_interval = 4 * 60 * 60 # YZ'den yağma listesini 4 saatte bir güncelle

        self.main_loop_interval_min = 5 * 60
        self.main_loop_interval_max = 10 * 60

        self.village_build_queues: Dict[str, List[Dict]] = {}
        self.village_troop_prefs: Dict[str, Dict] = {}


    def log_message_wrapper(self, message: str):
        if self.gui_logger_callback:
            self.gui_logger_callback(message)
        else:
            logger.info(message)


    def log_message(self, message: str, level: str = "info", exc_info=False): # Added exc_info for traceback logging
        log_method = getattr(logger, level, logger.info)
        log_method(message, exc_info=exc_info)

        if self.gui_logger_callback:
            # GUI logger might not support exc_info directly, adapt as needed
            if exc_info and isinstance(message, Exception):
                 self.gui_logger_callback(f"{message}\nSee console log for traceback.")
            else:
                 self.gui_logger_callback(message)


    def update_game_state(self):
        self.log_message("Oyun durumu güncelleniyor...")
        if not self.account_data or not self.client._is_active: # Check if client session is active
            self.log_message("Hesap verisi bulunamadı veya Travian istemcisi aktif değil. Durum güncellenemiyor.", level="warning")
            return

        if not self.account_data.villages:
            self.log_message("Hesapta köy verisi bulunamadı. İlk köy verisi çekilmeye çalışılıyor...", level="warning")
            initial_village = self.client.get_initial_village_data()
            if initial_village:
                self.account_data.villages.append(initial_village)
                self.log_message(f"İlk köy '{initial_village.name}' verileri çekildi.")
                if self.gui_logger_callback and hasattr(self.gui_logger_callback.__self__, 'update_all_gui_displays'):
                    self.gui_logger_callback.__self__.update_all_gui_displays()
            else:
                self.log_message("İlk köy verileri çekilemedi. Bot düzgün çalışmayabilir.", level="error")
                return

        for village in self.account_data.villages:
            self.log_message(f"Köy '{village.name}' (ID: {village.id}) için durum çekiliyor.")
            resources_data = self.client.get_village_resources(village.id)
            if resources_data:
                village.resources = {res: resources_data.get(res, 0) for res in ["wood", "clay", "iron", "crop"]}
                village.storage_capacity["warehouse"] = resources_data.get("warehouse_capacity", village.storage_capacity["warehouse"])
                village.storage_capacity["granary"] = resources_data.get("granary_capacity", village.storage_capacity["granary"])
                village.population = resources_data.get("population", village.population)
                # Assuming "free_crop" from client is what game_state.crop_consumption expects (Serbest Tahıl)
                village.crop_consumption = resources_data.get("free_crop", village.crop_consumption)
                village.production_rates["wood"] = resources_data.get("wood_prod", village.production_rates["wood"])
                village.production_rates["clay"] = resources_data.get("clay_prod", village.production_rates["clay"])
                village.production_rates["iron"] = resources_data.get("iron_prod", village.production_rates["iron"])
                village.production_rates["crop"] = resources_data.get("crop_prod", village.production_rates["crop"]) # Net crop prod
            else:
                self.log_message(f"Köy '{village.name}' için kaynaklar güncellenemedi.", level="warning")

            village.buildings = self.client.get_village_buildings(village.id)
            village.building_queue = self.client.get_building_queue(village.id)
            village.troops_home = self.client.get_troops_in_village(village.id) # Askerleri güncelle
            self.log_message(f"Köy '{village.name}' durumu güncellendi: {len(village.buildings)} bina, {len(village.building_queue)} kuyrukta, {sum(t.count for t in village.troops_home)} asker.")

        hero_status = self.client.get_hero_status()
        if hero_status:
            self.account_data.hero = hero_status
            self.log_message(f"Kahraman durumu güncellendi: Sağlık={hero_status.health}%, Macera={hero_status.adventure_available}")
        else:
            self.log_message("Kahraman durumu güncellenemedi.", level="warning")

        self.log_message("Oyun durumu güncelleme tamamlandı.")
        if self.gui_logger_callback and hasattr(self.gui_logger_callback.__self__, 'update_all_gui_displays'):
            self.gui_logger_callback.__self__.update_all_gui_displays()


    def manage_building_queues(self):
        self.log_message("Bina kuyrukları yönetiliyor...")
        if not self.client._is_active: return

        for village in self.account_data.villages:
            self.log_message(f"Köy '{village.name}' için inşaat kontrol ediliyor.")
            target_build_order = DEFAULT_BUILD_QUEUE_VILLAGE1 #

            active_constructions = len(village.building_queue)
            max_active_slots = 1 # TODO: Kabileye göre ayarla (örn: Romalı ise 2)

            if active_constructions >= max_active_slots:
                self.log_message(f"Köy '{village.name}': İnşaat kuyruğu dolu ({active_constructions}/{max_active_slots}).")
                continue

            for build_task in target_build_order:
                building_name = build_task["name"]
                target_level = build_task["target_level"]
                location_id = build_task.get("location_id")

                if not location_id:
                    self.log_message(f"'{building_name}' için konum ID'si eksik, atlanıyor.", level="warning")
                    continue

                current_building = village.get_building_by_location_id(location_id)
                current_level = 0
                if current_building:
                    current_level = current_building.level
                    if current_building.name != "Boş İnşaat Alanı" and current_building.name.lower() != building_name.lower() and current_level > 0 :
                        self.log_message(f"Konum {location_id}'de beklenen bina '{building_name}' yerine '{current_building.name}' var. Atlanıyor.", level="warning")
                        continue
                elif location_id and int(location_id) > 18 and building_name != "Boş İnşaat Alanı":
                     pass

                if current_level >= target_level:
                    continue

                self.log_message(f"Köy '{village.name}': '{building_name}' (Konum: {location_id}) seviye {current_level + 1}'e (hedef: {target_level}) yükseltiliyor.")
                if self.client.start_building_upgrade(building_name, location_id, village.id):
                    self.log_message(f"'{building_name}' (Konum: {location_id}) yükseltme talebi gönderildi.")
                    self.update_game_state()
                    break
                else:
                    self.log_message(f"'{building_name}' (Konum: {location_id}) yükseltilemedi.", level="warning")
        self.log_message("Bina kuyrukları yönetimi tamamlandı.")


    def manage_troop_training(self):
        self.log_message("Asker eğitimi yönetiliyor...")
        if not self.client._is_active: return

        for village in self.account_data.villages:
            self.log_message(f"Köy '{village.name}' için asker eğitimi kontrol ediliyor.")
            training_prefs_for_village = DEFAULT_TROOP_TRAINING_PREFS

            for troop_type, prefs in training_prefs_for_village.items():
                min_count = prefs["min_count"]
                train_amount = prefs["train_amount"]
                # building_gid = prefs["building_gid"] # This needs to be handled by client.train_troops

                current_troop_count = 0
                for troop_in_village in village.troops_home:
                    if troop_in_village.type_name.lower() == troop_type.lower():
                        current_troop_count = troop_in_village.count
                        break

                if current_troop_count < min_count:
                    amount_to_train = min(train_amount, min_count - current_troop_count)
                    if amount_to_train <= 0: continue

                    self.log_message(f"Köy '{village.name}': '{troop_type}' için yeterli asker yok ({current_troop_count}/{min_count}). {amount_to_train} adet eğitiliyor.")
                    # Pass troop_type and amount to a simplified train_troops
                    if self.client.train_troops(village.id, troop_type, amount_to_train):
                        self.log_message(f"{amount_to_train} adet '{troop_type}' eğitimi köy '{village.name}' için başlatıldı.")
                        self.update_game_state()
                        break
                    else:
                        self.log_message(f"'{troop_type}' eğitimi köy '{village.name}' için başlatılamadı.", level="warning")
        self.log_message("Asker eğitimi yönetimi tamamlandı.")


    def manage_hero_adventures(self):
        if not self.client._is_active: return
        if time.time() < self.next_adventure_check_time:
            return

        self.log_message("Kahraman maceraları kontrol ediliyor...")
        if not self.account_data.hero:
            self.log_message("Kahraman verisi bulunamadı.", level="warning")
            self.next_adventure_check_time = time.time() + self.adventure_cooldown_fail
            return

        hero = self.account_data.hero
        if hero.adventure_available:
            self.log_message("Kahraman için macera mevcut. Maceraya gönderiliyor...")
            if self.client.send_hero_to_adventure():
                self.log_message("Kahraman başarıyla maceraya gönderildi.")
                self.next_adventure_check_time = time.time() + self.adventure_cooldown_success
                self.account_data.hero.adventure_available = False # Update locally
            else:
                self.log_message("Kahraman maceraya gönderilemedi.", level="warning")
                self.next_adventure_check_time = time.time() + self.adventure_cooldown_fail
        else:
            self.log_message("Şu anda kahraman için uygun macera mevcut değil.")
            self.next_adventure_check_time = time.time() + self.adventure_cooldown_initial
        self.log_message("Kahraman maceraları kontrolü tamamlandı.")


    def update_farm_list_with_ai(self):
        if not self.client._is_active: return
        if time.time() < self.next_farm_list_ai_update_time:
            return

        self.log_message("YZ'den yeni yağma listesi önerileri alınması planlanıyor...")
        if not self.account_data.villages:
            self.log_message("Köy verisi yok, YZ'den yağma listesi alınamıyor.", level="warning")
            self.next_farm_list_ai_update_time = time.time() + self.ai_farm_update_interval
            return

        current_village = self.account_data.villages[0]
        self.log_message(f"YZ için '{current_village.name}' köyü etrafındaki bilgiler çekilecek.")

        nearby_villages_info = self.client.get_nearby_village_info(current_village.id, radius=7) #

        if nearby_villages_info:
            current_village_troops = current_village.troops_home
            self.log_message(f"YZ'ye sunulacak {len(nearby_villages_info)} köy/vaha bilgisi ve {len(current_village_troops)} tip asker bilgisi mevcut.")
            suggested_targets = self.ai_farm_list_manager.suggest_farm_targets(nearby_villages_info, current_village_troops)

            if suggested_targets:
                self.log_message(f"YZ'den {len(suggested_targets)} adet yağma hedefi önerisi alındı. FarmingManager'a iletiliyor.")
                self.farming_manager.set_farm_list(suggested_targets) #
            else:
                self.log_message("YZ'den bu sefer geçerli bir yağma hedefi önerisi alınamadı.", level="warning")
        else:
            self.log_message("Yakındaki köy/vaha bilgileri çekilemediği için YZ'ye soru sorulamıyor.", level="warning")

        self.next_farm_list_ai_update_time = time.time() + self.ai_farm_update_interval #
        self.log_message("YZ yağma listesi güncelleme işlemi tamamlandı.")


    def run(self):
        self.log_message("Bot motoru çalıştırılıyor...") # Changed message slightly

        # Login using the client IN THIS THREAD
        if not self.client.login(): # login() initializes Playwright in the current thread
            self.log_message("Bot motoru: TravianClient oturum açamadı. Bot durduruluyor.", level="error")
            # self.client.close() # login() attempts to close on failure
            self.is_running = False # Ensure if not already set by failed login's close
            return

        self.is_running = True # Set to true only after successful login
        self.log_message("TravianClient başarıyla oturum açtı. İlk durum güncellemesi yapılıyor...")

        self.update_game_state()
        self.next_adventure_check_time = time.time() + self.adventure_cooldown_initial

        while self.is_running:
            loop_start_time = time.time()
            try:
                self.log_message("Ana bot döngüsü başlıyor...")
                if not self.client._is_active: # Check if client session is still active
                    self.log_message("Travian istemci oturumu aktif değil. Yeniden bağlanmaya çalışılıyor...", level="warning")
                    if not self.client.login(): # Attempt to re-login
                        self.log_message("Yeniden bağlanma başarısız. Bot durduruluyor.", level="error")
                        self.is_running = False # Stop the bot
                        break # Exit while loop
                    self.log_message("Yeniden bağlanma başarılı.")

                self.update_game_state()
                if not self.is_running: break # Check after potentially long update

                self.update_farm_list_with_ai()
                if not self.is_running: break

                self.manage_building_queues()
                time.sleep(random.uniform(1,3))
                if not self.is_running: break

                self.manage_troop_training()
                time.sleep(random.uniform(1,3))
                if not self.is_running: break

                self.manage_hero_adventures()
                time.sleep(random.uniform(1,3))
                if not self.is_running: break

                self.farming_manager.automated_farming_cycle() #

                loop_end_time = time.time()
                processing_time = loop_end_time - loop_start_time
                sleep_duration = random.uniform(self.main_loop_interval_min, self.main_loop_interval_max)
                actual_sleep = max(0, sleep_duration - processing_time)

                self.log_message(f"Ana döngü tamamlandı ({processing_time:.2f} s). Sonraki kontrol ~{int(actual_sleep / 60)} dakika sonra.")

                for _ in range(int(actual_sleep)):
                    if not self.is_running:
                        break
                    time.sleep(1)
                if not self.is_running: break

            except PlaywrightError as pe: # Catch Playwright specific errors
                self.log_message(f"Bot motorunda bir Playwright hatası oluştu: {pe}", level="error", exc_info=True)
                self.log_message("Playwright hatası nedeniyle Travian istemcisi kapatılıyor.", level="warning")
                self.client.close() # Close the client as its Playwright instance is likely broken
                                     # The next loop iteration will attempt to re-login if self.is_running is still true
                if not self.is_running: break
                time.sleep(30) # Wait a bit before trying to recover in next loop

            except Exception as e:
                self.log_message(f"Bot motorunda beklenmedik bir genel hata oluştu: {e}", level="error", exc_info=True)
                if not self.is_running: break
                time.sleep(60) #

        self.log_message("Bot motoru döngüsü tamamlandı. Kaynaklar serbest bırakılıyor...")
        self.client.close() # Ensure client is closed when run loop exits
        self.log_message("Bot motoru durduruldu.")

    def stop(self):
        self.log_message("Bot motoru durdurulma isteği alındı...")
        self.is_running = False
        # Do not call client.close() here directly, run() method's finally block or end will handle it.
        # This prevents issues if stop() is called from a different thread than run().
