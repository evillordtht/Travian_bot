# --- travian_bot_project/gui/app_window.py ---
import customtkinter as ctk
import threading
import logging
import time
from typing import List, Dict, Optional, Any

from bot.travian_client import TravianClient
from bot.bot_engine import BotEngine, DEFAULT_BUILD_QUEUE_VILLAGE1 # Varsayılan inşaat listesini almak için
from bot.game_state import PlayerAccount, Village, Building, Troop, HeroStatus# Building, Troop, HeroStatus doğrudan kullanılmıyor
# from bot.farming_manager import FarmingManager # FarmingManager doğrudan GUI'de kullanılmıyor
# from bot.ai_farm_list_manager import AIFarmListManager # AIFarmListManager doğrudan GUI'de kullanılmıyor

logger = logging.getLogger(__name__)

class TravianBotApp(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title("Gelişmiş Travian Bot Arayüzü")
        self.geometry("1100x750") # Pencere boyutunu biraz büyütelim

        ctk.set_appearance_mode("System")  # "Dark", "Light" veya "System"
        ctk.set_default_color_theme("blue")  # Veya "green", "dark-blue"

        self.travian_client: Optional[TravianClient] = None
        self.bot_engine: Optional[BotEngine] = None
        self.bot_thread: Optional[threading.Thread] = None
        self.account_data: Optional[PlayerAccount] = None # BotEngine'e iletilecek

        self._setup_ui()
        # self._load_initial_credentials() # .env'den kimlik bilgisi yükleme kaldırıldı

    def _setup_ui(self):
        """Kullanıcı arayüzü bileşenlerini ayarlar."""
        self.grid_columnconfigure(0, weight=2) # Sol taraf (giriş, log)
        self.grid_columnconfigure(1, weight=3) # Sağ taraf (tablar)
        self.grid_rowconfigure(0, weight=0) # Giriş alanı için sabit
        self.grid_rowconfigure(1, weight=1) # Log alanı için genişleyebilir

        # Sol Bölüm: Giriş ve Loglar
        left_frame = ctk.CTkFrame(self)
        left_frame.grid(row=0, column=0, rowspan=2, padx=10, pady=10, sticky="nsew")
        left_frame.grid_rowconfigure(0, weight=0) # auth_frame
        left_frame.grid_rowconfigure(1, weight=1) # log_frame

        # 1. Kimlik Doğrulama Çerçevesi
        auth_frame = ctk.CTkFrame(left_frame)
        auth_frame.grid(row=0, column=0, padx=10, pady=10, sticky="ew")
        auth_frame.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(auth_frame, text="Sunucu URL:").grid(row=0, column=0, padx=5, pady=(10,5), sticky="w")
        self.server_url_entry = ctk.CTkEntry(auth_frame, placeholder_text="https://tsX.travian.com.tr")
        self.server_url_entry.grid(row=0, column=1, padx=5, pady=(10,5), sticky="ew")
        # Örnek sunucu URL'si
        self.server_url_entry.insert(0, "https://ts1.travian.com.tr")


        ctk.CTkLabel(auth_frame, text="Kullanıcı Adı:").grid(row=1, column=0, padx=5, pady=5, sticky="w")
        self.username_entry = ctk.CTkEntry(auth_frame, placeholder_text="Kullanıcı adınız")
        self.username_entry.grid(row=1, column=1, padx=5, pady=5, sticky="ew")

        ctk.CTkLabel(auth_frame, text="Şifre:").grid(row=2, column=0, padx=5, pady=5, sticky="w")
        self.password_entry = ctk.CTkEntry(auth_frame, show="*", placeholder_text="Şifreniz")
        self.password_entry.grid(row=2, column=1, padx=5, pady=5, sticky="ew")

        self.login_button = ctk.CTkButton(auth_frame, text="Giriş Yap", command=self.handle_login)
        self.login_button.grid(row=3, column=0, columnspan=2, padx=5, pady=(10,10))

        # 3. Log Görüntüleme Alanı
        log_frame = ctk.CTkFrame(left_frame)
        log_frame.grid(row=1, column=0, padx=10, pady=(0,10), sticky="nsew")
        log_frame.grid_rowconfigure(0, weight=1)
        log_frame.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(log_frame, text="Bot Aktiviteleri (Loglar):").pack(anchor="w", padx=5, pady=(5,0))
        self.log_textbox = ctk.CTkTextbox(log_frame, state="disabled", wrap="word", font=("Arial", 11))
        self.log_textbox.pack(expand=True, fill="both", padx=5, pady=5)


        # Sağ Bölüm: Kontrol ve Yapılandırma (Sekmeli görünüm)
        right_frame = ctk.CTkFrame(self)
        right_frame.grid(row=0, column=1, rowspan=2, padx=10, pady=10, sticky="nsew")
        right_frame.grid_rowconfigure(0, weight=1)
        right_frame.grid_columnconfigure(0, weight=1)

        self.tabview = ctk.CTkTabview(right_frame)
        self.tabview.pack(expand=True, fill="both", padx=5, pady=5)
        
        # Kontrol Sekmesi
        control_tab = self.tabview.add("Bot Kontrol")
        control_tab.grid_columnconfigure(0, weight=1)
        # control_tab.grid_rowconfigure((0,1,2,3), weight=0) # Butonlar ortalansın

        control_buttons_frame = ctk.CTkFrame(control_tab)
        control_buttons_frame.pack(pady=20)


        self.start_bot_button = ctk.CTkButton(control_buttons_frame, text="Botu Başlat", command=self.start_bot, state="disabled", width=150)
        self.start_bot_button.pack(side="left", padx=10, pady=10) 

        self.stop_bot_button = ctk.CTkButton(control_buttons_frame, text="Botu Durdur", command=self.stop_bot, state="disabled", width=150)
        self.stop_bot_button.pack(side="left", padx=10, pady=10)

        self.status_label = ctk.CTkLabel(control_tab, text="Durum: Boşta", font=("Arial", 14, "bold"))
        self.status_label.pack(pady=20)

        # Kaynak Görüntüleme Sekmesi
        resources_tab = self.tabview.add("Kaynaklar")
        resources_tab.grid_columnconfigure(0, weight=1)
        resources_tab.grid_rowconfigure(0, weight=1)
        self.resources_textbox = ctk.CTkTextbox(resources_tab, state="disabled", wrap="word", height=200, font=("Arial", 12))
        self.resources_textbox.pack(pady=10, padx=10, fill="both", expand=True)

        # İnşaat Sekmesi
        build_tab = self.tabview.add("İnşaat")
        build_tab.grid_columnconfigure(0, weight=1)
        build_tab.grid_rowconfigure(1, weight=1) # Textbox genişlesin

        ctk.CTkLabel(build_tab, text="Mevcut İnşaat Sırası (BotEngine Varsayılanı):").pack(pady=5, anchor="w", padx=10)
        self.build_queue_text = ctk.CTkTextbox(build_tab, state="disabled", wrap="word", height=150, font=("Arial", 11))
        self.build_queue_text.pack(pady=5, padx=10, fill="x")
        self.update_build_queue_display(DEFAULT_BUILD_QUEUE_VILLAGE1) # Başlangıçta varsayılanı göster [cite: 280]

        ctk.CTkLabel(build_tab, text="Devam Eden/Sıradaki İnşaatlar (Oyundan Alınan):").pack(pady=(10,0), anchor="w", padx=10)
        self.game_build_queue_text = ctk.CTkTextbox(build_tab, state="disabled", wrap="word", height=100, font=("Arial", 11))
        self.game_build_queue_text.pack(pady=5, padx=10, fill="x", expand=True)
        self.update_game_build_queue_display([]) # Başlangıçta boş


        # İnşaat ekleme alanı (Bu kısım daha sonra BotEngine'deki listeyi dinamik değiştirecek şekilde geliştirilebilir)
        # Şimdilik sadece BotEngine'deki DEFAULT_BUILD_QUEUE_VILLAGE1'i gösteriyoruz.
        # build_input_frame = ctk.CTkFrame(build_tab) [cite: 280]
        # build_input_frame.pack(fill="x", pady=10, padx=10) [cite: 280]
        # ... (build_input_frame içeriği - şimdilik kaldırıldı, BotEngine'deki liste yönetilecek) [cite: 281]


        # Asker Eğitimi Sekmesi
        troops_tab = self.tabview.add("Asker Eğitimi")
        troops_tab.grid_columnconfigure(0, weight=1)
        # troops_tab.grid_rowconfigure(X, weight=1) # Gerekirse

        ctk.CTkLabel(troops_tab, text="Asker Eğitim Tercihleri (BotEngine Varsayılanı):").pack(pady=5, anchor="w", padx=10)
        self.troop_prefs_text = ctk.CTkTextbox(troops_tab, state="disabled", wrap="word", height=100, font=("Arial", 11))
        self.troop_prefs_text.pack(pady=5, padx=10, fill="x")
        self.update_troop_prefs_display(DEFAULT_TROOP_TRAINING_PREFS if hasattr(self, 'bot_engine') and self.bot_engine else {})


        # Asker eğitimi için manuel giriş alanı (Bu da BotEngine'deki listeyi değiştirecek şekilde geliştirilebilir)
        # troop_input_frame = ctk.CTkFrame(troops_tab)
        # ...

        ctk.CTkLabel(troops_tab, text="Köydeki Mevcut Askerler (Oyundan Alınan):").pack(pady=(10,0), anchor="w", padx=10)
        self.village_troops_text = ctk.CTkTextbox(troops_tab, state="disabled", wrap="word", height=150, font=("Arial", 11))
        self.village_troops_text.pack(pady=5, padx=10, fill="both", expand=True)
        self.update_village_troops_display([])


        # Yağma Sekmesi (YZ Entegreli)
        farm_tab = self.tabview.add("Yağma (YZ)")
        farm_tab.grid_columnconfigure(0, weight=1)
        farm_tab.grid_rowconfigure(1, weight=1) # Textbox genişlesin [cite: 281]

        self.update_ai_farm_list_button = ctk.CTkButton(farm_tab, text="YZ'den Yeni Yağma Hedefleri Al", command=self.trigger_ai_farm_list_update, width=250)
        self.update_ai_farm_list_button.pack(pady=10, padx=10)

        ctk.CTkLabel(farm_tab, text="YZ Tarafından Önerilen Yağma Hedefleri:").pack(pady=5, anchor="w", padx=10)
        self.farm_targets_textbox = ctk.CTkTextbox(farm_tab, state="disabled", wrap="word", font=("Arial", 11))
        self.farm_targets_textbox.pack(pady=5, padx=10, fill="both", expand=True)
        self.update_farm_targets_display([]) # Başlangıçta boş [cite: 281]

    def update_all_gui_displays(self):
        """BotEngine'den gelen güncel verilerle tüm ilgili GUI alanlarını günceller."""
        if self.account_data and self.account_data.villages:
            # Şimdilik ilk köyü baz alıyoruz
            village = self.account_data.villages[0]
            self.update_resources_display(
                village.resources,
                village.storage_capacity,
                village.production_rates,
                village.population,
                village.crop_consumption
            )
            self.update_game_build_queue_display(village.building_queue)
            self.update_village_troops_display(village.troops_home)
            # Yağma listesi FarmingManager'dan alınabilir veya BotEngine üzerinden
            if self.bot_engine and self.bot_engine.farming_manager:
                 self.update_farm_targets_display(self.bot_engine.farming_manager.farm_list)

        # BotEngine'deki varsayılan inşaat ve asker listelerini de güncel tutabiliriz
        if self.bot_engine:
            self.update_build_queue_display(DEFAULT_BUILD_QUEUE_VILLAGE1) # Şimdilik sabit
            self.update_troop_prefs_display(DEFAULT_TROOP_TRAINING_PREFS) # Şimdilik sabit

    def update_build_queue_display(self, queue_data: List[Dict]):
        """BotEngine'deki planlanan inşaat kuyruğu metin kutusunu günceller."""
        self.build_queue_text.configure(state="normal")
        self.build_queue_text.delete("1.0", "end")
        if not queue_data:
            self.build_queue_text.insert("end", "Planlanan inşaat görevi yok.")
        else:
            for item in queue_data:
                self.build_queue_text.insert("end", f"- {item.get('name', 'Bilinmeyen')} -> Hedef Seviye {item.get('target_level', '?')} (Konum ID: {item.get('location_id', '?')})\n")
        self.build_queue_text.configure(state="disabled")

    def update_game_build_queue_display(self, game_queue_data: List[Building]): # Building objesi alır
        """Oyundan alınan gerçek zamanlı inşaat kuyruğunu günceller."""
        self.game_build_queue_text.configure(state="normal")
        self.game_build_queue_text.delete("1.0", "end")
        if not game_queue_data:
            self.game_build_queue_text.insert("end", "Oyunda aktif inşaat yok.")
        else:
            for building_obj in game_queue_data:
                remaining_time_str = time.strftime('%H:%M:%S', time.gmtime(building_obj.build_time_remaining or 0))
                self.game_build_queue_text.insert("end", f"- {building_obj.name} Seviye {building_obj.level} (Kalan Süre: {remaining_time_str})\n")
        self.game_build_queue_text.configure(state="disabled")


    def update_resources_display(self, resources: Dict, capacity: Dict, production: Dict, population: int, crop_consumption: int):
        """Kaynak, kapasite, üretim, nüfus ve tahıl tüketimi bilgilerini günceller."""
        self.resources_textbox.configure(state="normal")
        self.resources_textbox.delete("1.0", "end")
        text = (
            f"Kaynaklar:\n"
            f"  Odun: {resources.get('wood', 0):,} / {capacity.get('warehouse', 0):,}\n"
            f"  Tuğla: {resources.get('clay', 0):,} / {capacity.get('warehouse', 0):,}\n"
            f"  Demir: {resources.get('iron', 0):,} / {capacity.get('warehouse', 0):,}\n"
            f"  Tahıl: {resources.get('crop', 0):,} / {capacity.get('granary', 0):,}\n\n"
            f"Üretim Oranları (saatlik):\n"
            f"  Odun: {production.get('wood_prod', 0):,} | Tuğla: {production.get('clay_prod', 0):,}\n"
            f"  Demir: {production.get('iron_prod', 0):,} | Tahıl (Brüt): {production.get('crop_prod', 0):,}\n\n"
            f"Nüfus: {population:,}\n"
            f"Tahıl Tüketimi (saatlik): {crop_consumption:,}\n"
            f"Net Tahıl (saatlik): {(production.get('crop_prod', 0) - crop_consumption):,}"
        )
        self.resources_textbox.insert("end", text)
        self.resources_textbox.configure(state="disabled")

    def update_troop_prefs_display(self, troop_prefs: Dict):
        """BotEngine'deki asker eğitim tercihlerini GUI'de gösterir."""
        self.troop_prefs_text.configure(state="normal")
        self.troop_prefs_text.delete("1.0", "end")
        if not troop_prefs:
            self.troop_prefs_text.insert("end", "Asker eğitim tercihi tanımlanmamış.")
        else:
            for troop_type, prefs in troop_prefs.items():
                self.troop_prefs_text.insert("end", f"- {troop_type}: Min: {prefs['min_count']}, Basım: {prefs['train_amount']}\n")
        self.troop_prefs_text.configure(state="disabled")

    def update_village_troops_display(self, troops_data: List[Troop]): # Troop objesi alır
        """Köydeki mevcut askerleri GUI'de gösterir."""
        self.village_troops_text.configure(state="normal")
        self.village_troops_text.delete("1.0", "end")
        if not troops_data:
            self.village_troops_text.insert("end", "Köyde asker bulunmuyor.")
        else:
            for troop_obj in troops_data:
                self.village_troops_text.insert("end", f"- {troop_obj.type_name}: {troop_obj.count:,}\n")
        self.village_troops_text.configure(state="disabled")


    def log_to_gui(self, message: str):
        """Bot motorundan veya diğer modüllerden gelen mesajları GUI log alanına ekler."""
        if not self.log_textbox.winfo_exists(): return # Pencere kapatılmışsa hata vermesini engelle

        # Mesajları sınırlı sayıda tutmak için (performans)
        # current_log = self.log_textbox.get("1.0", "end-1c")
        # lines = current_log.splitlines()
        # if len(lines) > 200: # Son 200 satırı tut
        #    self.log_textbox.configure(state="normal")
        #    self.log_textbox.delete("1.0", f"{len(lines) - 200}.end")
        #    self.log_textbox.configure(state="disabled")

        self.log_textbox.configure(state="normal")
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
        self.log_textbox.insert("end", f"[{timestamp}] {message}\n")
        self.log_textbox.see("end")  # En sona kaydır [cite: 285]
        self.log_textbox.configure(state="disabled")

    def update_farm_targets_display(self, farm_list: List[Dict]):
        """YZ'den gelen veya manuel olarak ayarlanan yağma hedefleri metin kutusunu günceller."""
        self.farm_targets_textbox.configure(state="normal")
        self.farm_targets_textbox.delete("1.0", "end")
        if not farm_list:
            self.farm_targets_textbox.insert("end", "Yağma hedefi listesi boş.")
        else:
            for i, target in enumerate(farm_list):
                coords_str = f"({target.get('target_coords',{}).get('x','?')}, {target.get('target_coords',{}).get('y','?')})"
                troops_str = ", ".join([f"{k}:{v}" for k, v in target.get("troops", {}).items()])
                village_name = target.get('village_name', 'Bilinmeyen Köy')
                self.farm_targets_textbox.insert("end", f"{i+1}. Köy: {village_name} {coords_str}, Askerler: [{troops_str}]\n")
        self.farm_targets_textbox.configure(state="disabled")


    def handle_login(self): 
        server_url = self.server_url_entry.get().strip()
        username = self.username_entry.get().strip()
        password = self.password_entry.get() # Şifrede başta/sonda boşluk olmamalı

        if not all([server_url, username, password]):
            self.log_to_gui("Hata: Sunucu URL, kullanıcı adı ve şifre alanları boş bırakılamaz.")
            return

        self.log_to_gui(f"{server_url} adresine '{username}' kullanıcısı ile giriş yapılıyor...")
        self.status_label.configure(text="Durum: Giriş Yapılıyor...")
        self.login_button.configure(state="disabled") # Giriş sırasında tekrar tıklanmasın

        # Giriş işlemini ayrı bir thread'de çalıştırarak GUI'nin donmasını engelle
        login_thread = threading.Thread(target=self._perform_login, args=(server_url, username, password), daemon=True)
        login_thread.start()

    def _perform_login(self, server_url, username, password): 
        try:
            # Eğer mevcut bir client varsa kapat
            if self.travian_client:
                self.travian_client.close()

            self.travian_client = TravianClient(server_url, username, password)
            if self.travian_client.login(): 
                self.log_to_gui("Giriş başarılı.")
                self.status_label.configure(text=f"Durum: Giriş Yapıldı ({username}). Boşta.")
                self.start_bot_button.configure(state="normal") # Botu başlatma butonu aktif [cite: 287]
                self.stop_bot_button.configure(state="disabled")

                # Oyuncu hesap verilerini oluştur ve ilk köy bilgilerini çek
                self.account_data = PlayerAccount(username=username) # PlayerAccount oluştur [cite: 287]
                # BotEngine'i burada oluşturabiliriz, böylece ilk köy verilerini çekmeden önce var olur
                # Veya BotEngine'i start_bot içinde oluşturup account_data'yı oraya veririz.
                # Şimdilik start_bot içinde oluşturalım.

                # Giriş sonrası ilk köy verilerini çekip GUI'yi güncelleyelim
                initial_village = self.travian_client.get_initial_village_data()
                if initial_village:
                    if not self.account_data.villages: # Eğer liste boşsa ekle
                         self.account_data.villages.append(initial_village)
                    else: # Yoksa ilk köyü güncelle (birden fazla köy yönetimi için geliştirilebilir)
                         self.account_data.villages[0] = initial_village

                    self.log_to_gui(f"'{initial_village.name}' köyünün ilk verileri çekildi.")
                    self.update_all_gui_displays() # Tüm GUI alanlarını güncelle

                    # Başarılı giriş sonrası YZ'den ilk yağma listesini almaya çalış
                    # BotEngine henüz başlatılmadığı için bunu manuel tetikleyebiliriz
                    # Veya BotEngine başlatıldığında ilk iş olarak bunu yapmasını sağlayabiliriz.
                    # Şimdilik, BotEngine başlatıldığında yapmasını bekleyelim.
                    self.log_to_gui("Bot başlatıldığında YZ'den yağma listesi çekilecektir.")


                else:
                    self.log_to_gui("İlk köy verileri çekilemedi. Lütfen botu başlatmadan önce kontrol edin.", level="warning")
            else:
                self.log_to_gui("Giriş başarısız. Lütfen bilgilerinizi ve sunucu durumunu kontrol edin.")
                self.status_label.configure(text="Durum: Giriş Başarısız.")
                self.travian_client = None # Başarısız giriş sonrası client'ı temizle [cite: 287]
                self.login_button.configure(state="normal") # Tekrar giriş denenebilsin
        except Exception as e:
            self.log_to_gui(f"Giriş işlemi sırasında beklenmedik bir hata oluştu: {e}", level="error", exc_info=True)
            self.status_label.configure(text="Durum: Giriş Hatası.")
            if self.travian_client:
                self.travian_client.close()
            self.travian_client = None
            self.login_button.configure(state="normal")


    def start_bot(self): 
        if not self.travian_client or not self.travian_client.page: # Giriş yapılmamışsa veya sayfa yoksa
            self.log_to_gui("Hata: Botu başlatmadan önce başarılı bir şekilde giriş yapmalısınız.")
            return

        if not self.account_data or not self.account_data.villages:
            self.log_to_gui("Hata: Köy verileri yüklenemedi. Bot başlatılamıyor. Lütfen tekrar giriş yapmayı deneyin.", level="warning")
            # Tekrar ilk köy verilerini çekmeyi deneyebiliriz.
            initial_village = self.travian_client.get_initial_village_data()
            if initial_village:
                if not self.account_data: self.account_data = PlayerAccount(username=self.username_entry.get()) # Eğer yoksa oluştur
                if not self.account_data.villages: self.account_data.villages.append(initial_village)
                else: self.account_data.villages[0] = initial_village
                self.update_all_gui_displays()
            else:
                return # Hala köy verisi yoksa başlatma

        if self.bot_engine and self.bot_engine.is_running:
            self.log_to_gui("Bot zaten çalışıyor.")
            return

        self.log_to_gui("Bot motoru başlatılıyor...")
        self.status_label.configure(text="Durum: Çalışıyor...")
        self.start_bot_button.configure(state="disabled")
        self.stop_bot_button.configure(state="normal")
        self.login_button.configure(state="disabled") # Bot çalışırken tekrar giriş yapılamasın

        # PlayerAccount nesnesi daha önce _perform_login'de oluşturuldu.
        if not self.account_data: # Eğer bir şekilde oluşmamışsa (olmamalı)
            self.log_to_gui("Hata: Hesap verileri bulunamadı. Bot başlatılamıyor.", level="error")
            self.stop_bot_button.configure(state="disabled")
            self.start_bot_button.configure(state="normal") # Yeniden giriş denenebilir
            return

        self.bot_engine = BotEngine(self.travian_client, self.account_data, self.log_to_gui)
        self.bot_thread = threading.Thread(target=self.bot_engine.run, daemon=True)
        self.bot_thread.start()

    def stop_bot(self): 
        if self.bot_engine and self.bot_engine.is_running:
            self.log_to_gui("Bot motoru durduruluyor... Lütfen bekleyin.")
            self.bot_engine.stop() # is_running flag'ini false yapar [cite: 288]
            # Bot thread'inin bitmesini beklemek GUI'yi dondurabilir.
            # Daemon thread olduğu için ana program kapanınca kapanır.
            # Ancak, durumu hemen güncellemek için kısa bir bekleme ve kontrol eklenebilir.
            # time.sleep(self.bot_engine.main_loop_interval_max / 60 + 2) # En uzun döngü süresinden biraz fazla
            # if self.bot_thread and self.bot_thread.is_alive():
            #    self.log_to_gui("Bot thread'i hala çalışıyor, sonlanması bekleniyor...", level="warning")

        self.status_label.configure(text="Durum: Durduruldu.")
        self.start_bot_button.configure(state="normal" if self.travian_client and self.travian_client.page else "disabled")
        self.stop_bot_button.configure(state="disabled")
        self.login_button.configure(state="normal" if not (self.travian_client and self.travian_client.page) else "disabled") # Giriş yapılmışsa login disabled kalsın
        self.log_to_gui("Bot motoru durdurma komutu gönderildi.")


    def on_closing(self):
        """Pencere kapatıldığında çağrılır. Botu ve Playwright'ı güvenle kapatır."""
        self.log_to_gui("Uygulama kapatılıyor...")
        if self.bot_engine and self.bot_engine.is_running:
            self.log_to_gui("Çalışan bot motoru durduruluyor...")
            self.stop_bot() # Önce bot motorunu durdur
            if self.bot_thread and self.bot_thread.is_alive():
                self.log_to_gui("Bot thread'inin sonlanması için bekleniyor (en fazla 5sn)...")
                self.bot_thread.join(timeout=5) # 5 saniye kadar bekle
                if self.bot_thread.is_alive():
                     self.log_to_gui("Bot thread'i zamanında sonlanmadı.", level="warning")


        if self.travian_client:
            self.log_to_gui("Playwright kaynakları kapatılıyor...")
            self.travian_client.close() # Sonra Playwright'ı kapat [cite: 288]

        self.destroy() # GUI penceresini kapat
        # logging.shutdown() # Günlükleyicileri kapatmak için (genelde gerekmez)

    def add_build_task(self):
        """GUI'den yeni bir inşaat görevi ekler (Bu fonksiyon BotEngine'deki listeyi güncellemeli)."""
        # Bu fonksiyon şimdilik BotEngine'deki DEFAULT_BUILD_QUEUE_VILLAGE1 listesini
        # doğrudan güncellemiyor. Daha gelişmiş bir yapıda BotEngine'e bir metod eklenerek
        # çalışan botun inşaat sırası dinamik olarak güncellenebilir.
        self.log_to_gui("Manuel inşaat görevi ekleme özelliği henüz tam olarak entegre edilmedi.\nBotEngine'deki varsayılan sıra kullanılmaktadır.", level="info")
        # Örnek implementasyon (BotEngine'de bir metod olmalı):
        # name = self.new_build_name_entry.get()
        # ...
        # if self.bot_engine:
        #    self.bot_engine.add_manual_build_task(new_task)
        #    self.update_build_queue_display(self.bot_engine.get_current_build_queue_for_gui())


    def handle_train_troops(self):
        """GUI'den asker eğitimini başlatır (Bu fonksiyon BotEngine'deki tercihleri güncellemeli)."""
        self.log_to_gui("Manuel asker eğitimi başlatma/tercih değiştirme henüz tam entegre edilmedi.\nBotEngine'deki varsayılan tercihler kullanılmaktadır.", level="info")
        # troop_type = self.troop_type_entry.get()
        # ...
        # if self.bot_engine and self.account_data and self.account_data.villages:
        #    # self.bot_engine.add_manual_troop_training_task(...)


    def trigger_ai_farm_list_update(self):
        """YZ'den yağma listesi güncellemesini manuel olarak tetikler."""
        if not self.bot_engine:
            self.log_to_gui("Hata: Bot motoru başlatılmadı. YZ'den liste alınamaz.")
            return
        if not self.bot_engine.is_running:
            self.log_to_gui("Hata: Bot motoru çalışmıyor. YZ'den liste almak için botu başlatın.", level="warning")
            # return # Çalışmıyorsa da YZ'den liste çekmeye izin verilebilir (opsiyonel)

        self.log_to_gui("YZ'den yeni yağma listesi alımı manuel olarak tetikleniyor...")
        # Ayrı bir thread'de çalıştırmak GUI'nin donmasını önler
        # update_farm_list_with_ai zaten kendi içinde cooldown kontrolü yapıyor.
        # Manuel tetikleme bu cooldown'ı bypass etmeli mi? Şimdilik hayır.
        # Eğer bypass isteniyorsa, BotEngine'e yeni bir metod eklenebilir.
        threading.Thread(target=self.bot_engine.update_farm_list_with_ai, daemon=True).start() 
