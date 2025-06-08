# --- travian_bot_project/bot/travian_client.py ---
from playwright.sync_api import sync_playwright, Page, BrowserContext, Browser, Playwright, Error as PlaywrightError # Added Playwright
from typing import Optional, List, Dict, Any
from .game_state import Village, Building, Troop, HeroStatus
import time
import re
import logging
import random # get_nearby_village_info simülasyonu için
import json # JavaScript nesnesini ayrıştırmak için

logger = logging.getLogger(__name__)

class TravianClient:
    """
    Playwright kullanarak Travian sunucusuyla etkileşim kurar.
    Oturum açma, veri çekme ve oyun içi eylemleri gerçekleştirme işlemlerini yönetir.
    Playwright kaynaklarını başlatan ve sonlandıran thread tarafından kullanılmalıdır.
    """

    def __init__(self, server_url: str, username: str, password: str):
        # server_url should be the base URL, e.g., "https://ts50.x5.europe.travian.com"
        self.server_url = server_url.strip('/')
        self.username = username
        self.password = password
        self.playwright_instance: Optional[Playwright] = None # Changed from playwright_context
        self.browser: Optional[Browser] = None
        self.context: Optional[BrowserContext] = None
        self.page: Optional[Page] = None
        self.current_village_id: Optional[str] = None
        self._is_active: bool = False # To track if login was successful and resources are active

    def _clean_text_for_int(self, text: Optional[str]) -> str:
        if not text:
            return "0"
        cleaned = text.replace('.', '').replace(',', '')
        cleaned = re.sub(r'[\u202A-\u202F\u200E\u200F]', '', cleaned)
        cleaned = cleaned.replace('\xa0', '')
        return cleaned.strip()

    def _get_safe_int_from_text(self, text: Optional[str], resource_name: str = "Değer", default_value: int = 0) -> int:
        cleaned_text = self._clean_text_for_int(text)
        try:
            if re.fullmatch(r'-?\d+', cleaned_text):
                return int(cleaned_text)
            else:
                logger.debug(f"'{resource_name}' için metin sayısal değil: '{text}'. Varsayılan ({default_value}) kullanılıyor.")
                return default_value
        except ValueError:
            logger.warning(f"'{resource_name}' metinden dönüştürülemedi. Değer: '{text}'. Varsayılan ({default_value}) kullanılıyor.")
            return default_value

    def _get_safe_int_from_locator(self, locator_selector: str, resource_name: str, attribute: Optional[str] = None, default_value: int = 0) -> int:
        if not self.page:
            logger.error(f"'{resource_name}' çekilemedi: Sayfa mevcut değil.")
            return default_value
        try:
            element = self.page.locator(locator_selector).first
            if not element.is_visible(timeout=2000):
                logger.debug(f"'{resource_name}' için element ({locator_selector}) görünür değil veya bulunamadı.")
                return default_value
            
            raw_text: Optional[str]
            if attribute:
                raw_text = element.get_attribute(attribute)
            else:
                raw_text = element.inner_text()

            return self._get_safe_int_from_text(raw_text, resource_name, default_value)
        except PlaywrightError as e:
            logger.warning(f"'{resource_name}' ({locator_selector}) çekilirken Playwright hatası (örn. zaman aşımı): {e}. Varsayılan ({default_value}) kullanılıyor.")
            return default_value
        except Exception as e:
            logger.error(f"'{resource_name}' ({locator_selector}) çekilirken genel hata: {e}", exc_info=True)
            return default_value

    def login(self) -> bool:
        # This method should be called from the thread that will perform Playwright operations
        if self._is_active:
            logger.info("Zaten aktif bir oturum var. Önce kapatılıyor...")
            self.close() # Close existing session before starting a new one

        try:
            logger.info("Playwright başlatılıyor...")
            self.playwright_instance = sync_playwright().start() # START PLAYWRIGHT IN CURRENT THREAD
            logger.info(f"Playwright başlatıldı: {self.playwright_instance}")

            self.browser = self.playwright_instance.chromium.launch(headless=True, slow_mo=50) # headless=True olarak ayarlandı, slow_mo isteğe bağlı düşürülebilir
            self.context = self.browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/100.0.4896.127 Safari/537.36"
            )
            self.context.set_default_timeout(40000)
            self.page = self.context.new_page()
            
            # Navigate to the base URL, assuming it redirects to login or is the login page.
            # Travian often has login on the main page or /dorf1.php if not logged in.
            login_page_url = f"{self.server_url}/" # Or specific login path e.g. /login.php
            logger.info(f"{login_page_url} adresine gidiliyor...")
            self.page.goto(login_page_url, wait_until="domcontentloaded")

            # Check if already logged in (e.g., by looking for dorf1.php in URL or a logout button)
            # This simple check might need to be more robust
            if "dorf1.php" in self.page.url:
                logger.info("Giriş yapılmış gibi görünüyor (dorf1.php URL'de).")
                self._update_current_village_id_after_login()
                if self.current_village_id:
                    self._is_active = True
                    logger.info("Giriş başarılı (zaten giriş yapılmış).")
                    return True
                else: # On dorf1 but couldn't get village ID, something is wrong
                    logger.warning("dorf1.php'de ama köy ID alınamadı, normal giriş denenecek.")


            logger.info("Kullanıcı adı ve şifre giriliyor...")
            # Common login field names, adjust if server specific
            user_input_selector = "input[name='name'], input[name='user'], input#user"
            pw_input_selector = "input[name='password'], input[name='pass'], input#pass"
            
            if self.page.locator(user_input_selector).first.is_visible(timeout=5000):
                 self.page.locator(user_input_selector).first.fill(self.username)
                 self.page.locator(pw_input_selector).first.fill(self.password)
            else:
                logger.error("Kullanıcı adı veya şifre giriş alanı bulunamadı.")
                self.close()
                return False


            logger.info("Giriş butonuna tıklanıyor...")
            # Common login button selectors
            login_button_s1 = self.page.locator("button#s1, button.green[type='submit']") # Travian specific + general
            login_button_submit = self.page.locator("button[type='submit'], input[type='submit']")


            clicked_button = False
            if login_button_s1.first.is_visible(timeout=3000):
                login_button_s1.first.click()
                clicked_button = True
            elif login_button_submit.first.is_visible(timeout=3000):
                logger.info("İlk giriş butonu bulunamadı, alternatif submit butonu denenecek.")
                login_button_submit.first.click()
                clicked_button = True
            else:
                logger.error("Giriş butonu bulunamadı.")
                self.close()
                return False
            
            if clicked_button:
                logger.info("Giriş sonrası yönlendirme bekleniyor (dorf1.php)...")
                try:
                    self.page.wait_for_url(f"**{self.server_url}**/dorf1.php**", timeout=45000)
                    logger.info("Giriş başarılı.")
                    self._update_current_village_id_after_login()
                    self._is_active = True
                    return True
                except PlaywrightError as e:
                    logger.error(f"Giriş sonrası dorf1.php'ye yönlendirme beklenirken hata: {e}")
                    # Check if it's a different success page or if login failed
                    if "logout.php" in self.page.content(): # Check for logout button as sign of success
                         logger.info("dorf1.php'ye yönlendirilmedi ama çıkış butonu bulundu, giriş başarılı sayılıyor.")
                         self._update_current_village_id_after_login() # May not be on dorf1
                         self._is_active = True
                         return True
                    logger.error(f"Giriş başarısız oldu. Sayfa URL: {self.page.url}, Sayfa içeriği (ilk 500 karakter): {self.page.content()[:500]}")
                    self.close()
                    return False
            else: # Should not happen if button locators are correct and one was found
                 logger.error("Giriş butonu tıklanamadı.")
                 self.close()
                 return False

        except PlaywrightError as e:
            logger.error(f"Playwright ile ilgili bir giriş hatası oluştu: {e}", exc_info=True)
            self.close()
            return False
        except Exception as e:
            logger.error(f"Giriş sırasında genel bir hata oluştu: {e}", exc_info=True)
            self.close()
            return False

    def _update_current_village_id_after_login(self):
        if not self.page or not self._is_active:
            logger.warning("Sayfa yok veya aktif oturum yok, köy ID'si güncellenemiyor.")
            return
        try:
            # Ensure on dorf1 or a page where village list is visible
            if "dorf1.php" not in self.page.url and "dorf2.php" not in self.page.url:
                logger.info(f"Köy ID'si güncellemek için dorf1.php'ye gidiliyor. Mevcut URL: {self.page.url}")
                self.page.goto(f"{self.server_url}/dorf1.php", wait_until="domcontentloaded", timeout=15000)


            active_village_element = self.page.locator("div#sidebarBoxVillageList div.listEntry.village.active")
            if active_village_element.is_visible(timeout=5000):
                did = active_village_element.get_attribute("data-did")
                if did:
                    self.current_village_id = did
                    logger.info(f"Aktif köy ID'si 'data-did' attribute'undan alındı: {self.current_village_id}")
                    return

            current_url = self.page.url
            match = re.search(r'[?&](newdid|did)=(\d+)', current_url) # Check for newdid or did
            if match:
                self.current_village_id = match.group(2)
                logger.info(f"Aktif köy ID'si URL'den alındı: {self.current_village_id}")
                return
            
            logger.warning("Aktif köy ID'si `_update_current_village_id_after_login` ile alınamadı. `current_village_id` None olarak kaldı.")
            self.current_village_id = None

        except Exception as e:
            logger.warning(f"Aktif köy ID'si alınırken hata: {e}", exc_info=True)
            self.current_village_id = None

    def close(self):
        if not self.playwright_instance and not self._is_active:
            logger.info("Playwright kaynakları zaten kapalı veya hiç başlatılmadı.")
            return

        logger.info("Playwright kaynakları kapatılıyor...")
        self._is_active = False # Mark as inactive before attempting to close
        
        # It's important that these are called from the same thread that started Playwright
        if self.page:
            try: self.page.close()
            except Exception as e: logger.warning(f"Sayfa kapatılırken hata: {e}")
        if self.context:
            try: self.context.close()
            except Exception as e: logger.warning(f"Tarayıcı context'i kapatılırken hata: {e}")
        if self.browser:
            try: self.browser.close()
            except Exception as e: logger.warning(f"Tarayıcı kapatılırken hata: {e}")
        if self.playwright_instance:
            try:
                logger.info(f"Playwright durduruluyor: {self.playwright_instance}")
                self.playwright_instance.stop()
                logger.info("Playwright durduruldu.")
            except Exception as e: logger.warning(f"Playwright context'i durdurulurken hata: {e}")
        
        self.page, self.context, self.browser, self.playwright_instance = None, None, None, None
        logger.info("Playwright kaynakları temizlendi.")


    def navigate_to_village(self, village_id: str):
        if not self.page or not self._is_active:
            logger.error("Sayfa mevcut değil veya aktif oturum yok. Navigasyon yapılamıyor.")
            return
        try:
            target_url_with_did = f"{self.server_url}/dorf1.php?newdid={village_id}"
            
            current_url_path = self.page.url.split('?')[0]
            current_newdid_match = re.search(r'[?&]newdid=(\d+)', self.page.url)
            current_page_newdid = current_newdid_match.group(1) if current_newdid_match else None

            if not current_url_path.endswith("dorf1.php") or current_page_newdid != village_id:
                logger.info(f"Köy ID {village_id} ({target_url_with_did}) adresine gidiliyor.")
                self.page.goto(target_url_with_did, wait_until="domcontentloaded")
                self.current_village_id = village_id # Update current village ID upon successful navigation
            else:
                logger.info(f"Zaten köy ID {village_id} ({self.page.url}) dorf1.php sayfasındayız.")
        except Exception as e:
            logger.error(f"Köy {village_id} navigasyonunda hata: {e}", exc_info=True)


    def get_village_resources(self, village_id: Optional[str] = None) -> Optional[Dict[str, int]]:
        if not self.page or not self._is_active:
            logger.error("Sayfa mevcut değil veya aktif oturum yok. Kaynaklar çekilemiyor."); return None
        
        target_village_id = village_id or self.current_village_id
        if not target_village_id: logger.error("Kaynak çekmek için köy ID'si belirlenemedi."); return None
        
        try:
            # Ensure we are on the dorf1 page of the target village
            current_page_did_match = re.search(r'[?&]newdid=(\d+)', self.page.url)
            current_page_did = current_page_did_match.group(1) if current_page_did_match else None
            current_url_path = self.page.url.split('?')[0]

            if not current_url_path.endswith("dorf1.php") or current_page_did != target_village_id:
                self.navigate_to_village(target_village_id)
                if not self.page.url.split('?')[0].endswith("dorf1.php"): # Check if navigation was successful
                    logger.error(f"Köy {target_village_id} dorf1.php sayfasına navigasyon başarısız.")
                    return None
            else: # Already on correct village's dorf1, reload to get fresh data
                logger.info(f"Köy {target_village_id} için dorf1.php sayfası yenileniyor...")
                self.page.reload(wait_until="domcontentloaded")

            resources_data = {}
            
            try:
                logger.debug("JavaScript kaynak nesnesi aranıyor...")
                all_scripts = self.page.query_selector_all("script")
                script_content_raw = None
                for script_tag in all_scripts:
                    content = script_tag.inner_text()
                    if "var resources = {" in content and "maxStorage" in content and "production" in content:
                        script_content_raw = content
                        logger.debug("Potansiyel kaynak JavaScript bloğu bulundu.")
                        break
                
                if script_content_raw:
                    match_js = re.search(r'var\s+resources\s*=\s*(\{[\s\S]*?\})\s*;?\s*(var\s+maxStorage\s*=\s*(\{[\s\S]*?\})\s*;?)?\s*(var\s+production\s*=\s*(\{[\s\S]*?\})\s*;?)?', script_content_raw)
                    if match_js:
                        resources_json_str = match_js.group(1)
                        max_storage_json_str = match_js.group(3) if match_js.group(2) else None
                        production_json_str = match_js.group(5) if match_js.group(4) else None

                        # Convert JS object literal to valid JSON (heuristic)
                        def js_to_json_like(js_obj_str):
                            if not js_obj_str: return None
                            # Add quotes around keys
                            s = re.sub(r'([{,]\s*)([a-zA-Z_]\w*)(\s*:)', r'\1"\2"\3', js_obj_str)
                            return s

                        js_data_res = json.loads(js_to_json_like(resources_json_str))
                        js_data_max_storage = json.loads(js_to_json_like(max_storage_json_str)) if max_storage_json_str else js_data_res.get("maxStorage", {}) # Fallback if not separate
                        js_data_prod = json.loads(js_to_json_like(production_json_str)) if production_json_str else js_data_res.get("production", {}) # Fallback

                        # It seems 'resources' contains 'storage', 'maxStorage', 'production' in some game versions
                        storage_obj = js_data_res.get('storage', js_data_res) # If 'storage' key exists, use it, else assume top level
                        
                        resources_data['wood'] = self._get_safe_int_from_text(str(storage_obj.get('l1')), "Odun (JS)")
                        resources_data['clay'] = self._get_safe_int_from_text(str(storage_obj.get('l2')), "Tuğla (JS)")
                        resources_data['iron'] = self._get_safe_int_from_text(str(storage_obj.get('l3')), "Demir (JS)")
                        resources_data['crop'] = self._get_safe_int_from_text(str(storage_obj.get('l4')), "Tahıl (JS)")

                        resources_data['warehouse_capacity'] = self._get_safe_int_from_text(str(js_data_max_storage.get('l1')), "Ambar Kapasitesi (JS)")
                        resources_data['granary_capacity'] = self._get_safe_int_from_text(str(js_data_max_storage.get('l4')), "Tahıl Ambarı Kapasitesi (JS)")
                        
                        resources_data['wood_prod'] = self._get_safe_int_from_text(str(js_data_prod.get('l1')), "Odun Üretimi (JS)")
                        resources_data['clay_prod'] = self._get_safe_int_from_text(str(js_data_prod.get('l2')), "Tuğla Üretimi (JS)")
                        resources_data['iron_prod'] = self._get_safe_int_from_text(str(js_data_prod.get('l3')), "Demir Üretimi (JS)")
                        # l4 is net crop, l5 is free crop (consumption)
                        resources_data['crop_prod'] = self._get_safe_int_from_text(str(js_data_prod.get('l4')), "Net Tahıl Üretimi (JS)") # Net production
                        resources_data['crop_consumption'] = self._get_safe_int_from_text(str(js_data_prod.get('l5')), "Tahıl Tüketimi / Serbest Tahıl (JS)") # Actually free crop or consumption?
                        # The game state `crop_consumption` should be actual consumption. `free_crop` is usually `production - consumption`.
                        # If l5 is "free crop", then actual consumption = (gross production) - free_crop.
                        # Gross production for crop is not directly in l1-l5 production usually.
                        # For now, let's assume l4 is net, and we need gross crop to calculate consumption if l5 is free_crop.
                        # Or, if l5 means something else (e.g. raw consumption value shown as negative).
                        # Let's assume for now `crop_prod_net` is `resources_data['crop_prod']`
                        # and `free_crop` (which is `l5` in Travian JS) is what `game_state.Village.crop_consumption` expects as "Serbest Tahıl"
                        # This means `game_state.Village.crop_consumption` might be misnamed. It should be `free_crop_production`.
                        # Let's map l5 to 'free_crop' for now, and game_state can be adjusted.
                        resources_data['free_crop'] = resources_data['crop_consumption'] # Keep original mapping intent from logs

                        logger.info(f"Kaynaklar köy {target_village_id} için JavaScript nesnesinden başarıyla çekildi.")
                    else:
                         logger.warning("JavaScript 'resources' nesnesi regex ile eşleşmedi.")
                         raise ValueError("JavaScript 'resources' nesnesi bulunamadı veya formatı beklenenden farklı.")
                else:
                    logger.warning("Kaynakları içeren JavaScript bloğu bulunamadı.")
                    raise ValueError("Kaynakları içeren JavaScript bloğu bulunamadı.")

            except Exception as js_e:
                logger.warning(f"JavaScript kaynak nesnesi ayrıştırılamadı ({js_e}), HTML elementlerine fallback yapılıyor.")
                resources_data['wood'] = self._get_safe_int_from_locator("div#l1.value, span#l1", "Odun (HTML)")
                resources_data['clay'] = self._get_safe_int_from_locator("div#l2.value, span#l2", "Tuğla (HTML)")
                resources_data['iron'] = self._get_safe_int_from_locator("div#l3.value, span#l3", "Demir (HTML)")
                resources_data['crop'] = self._get_safe_int_from_locator("div#l4.value, span#l4", "Tahıl (HTML)")

                resources_data['warehouse_capacity'] = self._get_safe_int_from_locator("div#stockBar div.warehouse div.capacity div.value, #stockBarWarehouse .capacity", "Ambar Kapasitesi (HTML)", default_value=800)
                resources_data['granary_capacity'] = self._get_safe_int_from_locator("div#stockBar div.granary div.capacity div.value, #stockBarGranary .capacity", "Tahıl Ambarı Kapasitesi (HTML)", default_value=800)
            
                prod_table = self.page.locator("table#production")
                if prod_table.is_visible(timeout=1000):
                    resources_data['wood_prod'] = self._get_safe_int_from_locator("table#production tbody tr:nth-child(1) td.num", "Odun Üretimi (HTML)")
                    resources_data['clay_prod'] = self._get_safe_int_from_locator("table#production tbody tr:nth-child(2) td.num", "Tuğla Üretimi (HTML)")
                    resources_data['iron_prod'] = self._get_safe_int_from_locator("table#production tbody tr:nth-child(3) td.num", "Demir Üretimi (HTML)")
                    resources_data['crop_prod'] = self._get_safe_int_from_locator("table#production tbody tr:nth-child(4) td.num", "Net Tahıl Üretimi (HTML)") # Net
                else: # Fallback for production if table not found
                    logger.warning("Üretim tablosu (table#production) bulunamadı. Üretim değerleri sıfır olarak ayarlanıyor.")
                    for key in ['wood_prod', 'clay_prod', 'iron_prod', 'crop_prod']: resources_data[key] = 0
                
                # Free crop (or consumption)
                # Travian usually shows "Free crop" / "Serbest Tahıl". If it's consumption, it's often negative.
                # Selectors might be #stockBarFreeCrop span.value or similar
                resources_data['free_crop'] = self._get_safe_int_from_locator("#stockBarFreeCrop span.value, span#stockBarFreeCrop", "Serbest Tahıl (HTML)")
                # If free_crop is consumption, it's usually total_prod - actual_consumption, or just actual_consumption if negative.
                # The provided `game_state.Village.crop_consumption` is used for "Serbest Tahıl" in original logs.
                # So we assume `free_crop` is the value for "Serbest Tahıl".
                # `game_state.crop_consumption` should ideally store the actual troop consumption.
                # For now, we keep the mapping from logs: `resources_data.get("crop_consumption", ...)` from bot_engine refers to this 'free_crop'.


            # Population
            pop_selector = "div#sidebarBoxActiveVillage div.population span, span.population-value" # Common selectors
            resources_data['population'] = self._get_safe_int_from_locator(pop_selector, "Nüfus")

            logger.info(f"Son kaynaklar (köy {target_village_id}): {resources_data}")
            return resources_data
            
        except Exception as e:
            logger.error(f"Kaynakları köy {target_village_id} için çekerken genel hata: {e}", exc_info=True)
            return None

    def get_initial_village_data(self) -> Optional[Village]:
        if not self.page or not self._is_active:
            logger.error("Sayfa mevcut değil veya aktif oturum yok. Önce giriş yapın."); return None
        try:
            logger.info("İlk köy verileri çekiliyor...")
            if not self.current_village_id:
                logger.info("Mevcut köy ID'si yok, güncellenmeye çalışılıyor...")
                self.navigate_to_village(self.current_village_id or "0") # Try navigating to dorf1 generally if no ID
                self._update_current_village_id_after_login() # Attempt to get it
                if not self.current_village_id:
                    logger.error("Aktif köy ID'si belirlenemedi. İlk köy verileri çekilemiyor.")
                    return None
            
            village_id = self.current_village_id
            # Ensure we are on dorf1 for the current village
            self.navigate_to_village(village_id)
            if not self.page.url.split('?')[0].endswith("dorf1.php"):
                 logger.error(f"İlk köy verileri için dorf1.php (köy {village_id}) navigasyonu başarısız.")
                 return None
            
            village_name_input = self.page.locator("div#sidebarBoxActiveVillage div#villageName input.villageInput")
            village_name_text_fallback = self.page.locator("div#sidebarBoxActiveVillage div.name")

            village_name = "Bilinmeyen Köy"
            if village_name_input.is_visible(timeout=1000):
                 village_name = village_name_input.get_attribute("value", timeout=1000).strip()
            elif village_name_text_fallback.is_visible(timeout=1000):
                 village_name = village_name_text_fallback.inner_text(timeout=1000).strip()


            active_village_entry = self.page.locator(f"div#sidebarBoxVillageList div.listEntry.village.active[data-did='{village_id}']")
            coords_x, coords_y = None, None
            if active_village_entry.is_visible(timeout=1000):
                coords_x_text = active_village_entry.locator("span.coordinateX").inner_text()
                coords_y_text = active_village_entry.locator("span.coordinateY").inner_text()
                coords_x = self._get_safe_int_from_text(coords_x_text, "Koordinat X")
                coords_y = self._get_safe_int_from_text(coords_y_text, "Koordinat Y")
            
            coordinates = {"x": coords_x, "y": coords_y} if coords_x is not None and coords_y is not None else None

            resources_info = self.get_village_resources(village_id)
            if not resources_info:
                logger.warning(f"Köy {village_id} için kaynaklar çekilemedi. Varsayılan boş değerler kullanılacak.")
                resources_info = {} # ensure it's a dict for .get() calls

            # Note: `game_state.Village.crop_consumption` seems to be used for "Free Crop" based on BotEngine logic.
            # If it's meant to be actual troop consumption, calculation is needed: GrossCropProd - FreeCrop = Consumption.
            # Here, we map "free_crop" from resources_info to game_state's `crop_consumption` to match existing BotEngine usage.
            # If `game_state.production_rates["crop"]` is NET production, then GrossCropProd = NetCropProd + ActualConsumption.

            village = Village(
                name=village_name, id=village_id, coordinates=coordinates,
                resources={
                    "wood": resources_info.get("wood", 0), "clay": resources_info.get("clay", 0),
                    "iron": resources_info.get("iron", 0), "crop": resources_info.get("crop", 0)
                },
                storage_capacity={
                    "warehouse": resources_info.get("warehouse_capacity", 800),
                    "granary": resources_info.get("granary_capacity", 800)
                },
                production_rates={ # Ensure these are GROSS production rates if possible, or clearly document if NET
                    "wood": resources_info.get("wood_prod", 0), "clay": resources_info.get("clay_prod", 0),
                    "iron": resources_info.get("iron_prod", 0), "crop": resources_info.get("crop_prod", 0) # This is NET from JS
                },
                buildings=self.get_village_buildings(village_id),
                building_queue=self.get_building_queue(village_id),
                population=resources_info.get("population", 0),
                crop_consumption=resources_info.get("free_crop", 0), # This is 'Serbest Tahıl' or 'Free Crop'
                troops_home=self.get_troops_in_village(village_id)
            )
            logger.info(f"İlk köy verileri başarıyla çekildi: {village.name} (ID: {village.id})")
            return village
        except Exception as e:
            logger.error(f"İlk köy verilerini çekerken hata: {e}", exc_info=True)
            return None

    def get_village_buildings(self, village_id: Optional[str] = None) -> List[Building]:
        if not self.page or not self._is_active:
            logger.error("Sayfa mevcut değil veya aktif oturum yok. Binalar çekilemiyor."); return []

        target_village_id = village_id or self.current_village_id
        if not target_village_id: logger.error("Bina çekmek için köy ID'si belirlenemedi."); return []
        
        buildings: List[Building] = []
        try:
            # 1. Kaynak Alanları (dorf1.php)
            logger.info(f"Kaynak alanı binaları dorf1.php'den (köy ID: {target_village_id}) çekiliyor...")
            self.navigate_to_village(target_village_id) # Ensures on dorf1
            if not self.page.url.split('?')[0].endswith("dorf1.php"):
                 logger.error(f"Kaynak alanı için dorf1.php (köy {target_village_id}) navigasyonu başarısız.")
                 return []

            # Selector for resource fields. Needs verification against actual game HTML.
            resource_field_elements = self.page.locator("div#resourceFieldContainer a.resourceField[data-aid]")
            count = resource_field_elements.count()
            logger.info(f"{count} kaynak alanı elementi bulundu (Selektör: div#resourceFieldContainer a.resourceField[data-aid]).")

            for i in range(count):
                element = resource_field_elements.nth(i)
                try:
                    location_id = element.get_attribute("data-aid")
                    gid = element.get_attribute("data-gid") # Building type ID
                    title_text = element.get_attribute("title") or ""
                    class_attr = element.get_attribute("class") or ""

                    name = f"Kaynak GID {gid}" # Default name
                    level = 0
                    
                    # Try to parse name and level from title (e.g., "Woodcutter <span class='level'>Level 2</span>||Upgrade to level 3...")
                    # This parsing is fragile and highly dependent on game localization and HTML structure.
                    title_main_part = title_text.split("||")[0]
                    name_match_html = re.match(r'(.+?)<span class="level">Seviye\s*(\d+)</span>', title_main_part, re.IGNORECASE)
                    name_match_simple = re.match(r'(.+?)\s+Seviye\s*(\d+)', title_main_part, re.IGNORECASE)

                    if name_match_html:
                        name = name_match_html.group(1).strip()
                        level = int(name_match_html.group(2))
                    elif name_match_simple:
                        name = name_match_simple.group(1).strip()
                        level = int(name_match_simple.group(2))
                    elif title_main_part and "Seviye" not in title_main_part : # e.g. "Woodcutter" (level 0 or not shown)
                        name = title_main_part.strip()
                        level = 0 # Assume 0 if not specified in title and no level class found later

                    # Override or confirm level from class attribute (e.g., class="... level5 ...")
                    level_class_match = re.search(r'\blevel(\d+)\b', class_attr)
                    if level_class_match:
                        level_from_class = int(level_class_match.group(1))
                        if level_from_class > level : # Prefer higher level if discrepancy, or if title parsing failed
                            level = level_from_class
                        if name == f"Kaynak GID {gid}" and title_main_part: # if name parsing failed but title exists
                            name = title_main_part.split("<span")[0].strip() or f"Kaynak GID {gid} L{level}"


                    # Basic check if it's a known building type or just an empty plot to be built
                    if name == f"Kaynak GID {gid}" and gid == "0": # GID 0 is often an empty plot
                        name = "Boş Alan (Kaynak)"

                    is_under_construction = "underConstruction" in class_attr
                    
                    if location_id: # Must have location_id
                         buildings.append(Building(name=name, level=level, location_id=location_id, gid=gid)) # Removed is_under_construction from dataclass
                         logger.debug(f"Kaynak alanı eklendi: Name='{name}', Level={level}, LocID='{location_id}', GID='{gid}', UnderConstruction={is_under_construction}")
                    else:
                        logger.warning(f"Kaynak alanı atlanıyor (konum ID yok): title='{title_text}', class='{class_attr}'")
                except Exception as field_e:
                    logger.debug(f"Kaynak alanı (index {i}) ayrıştırılamadı: {field_e}. Element HTML (outer): {element.evaluate('node => node.outerHTML') if element else 'N/A'}")
            
            logger.info(f"{len(buildings)} kaynak alanı binası çekildi.")
            initial_building_count = len(buildings)

            # 2. Köy Merkezi Binaları (dorf2.php)
            logger.info(f"Köy merkezi binaları dorf2.php'den (köy ID: {target_village_id}) çekiliyor...")
            self.page.goto(f"{self.server_url}/dorf2.php?newdid={target_village_id}", wait_until="domcontentloaded")
            self.current_village_id = target_village_id # Update current village ID

            # Selector for building slots in village center. Needs verification.
            building_slot_elements = self.page.locator("div#villageContent div.buildingSlot[data-gid], map#map2 area[gid]") # Common patterns
            count_dorf2 = building_slot_elements.count()
            logger.info(f"dorf2'de {count_dorf2} potansiyel bina slotu/alanı bulundu.")
            
            for i in range(count_dorf2):
                element = building_slot_elements.nth(i)
                try:
                    gid = element.get_attribute("data-gid")
                    if not gid or gid == "0": # Skip empty slots
                        continue

                    # Name from title attribute (e.g., "Main Building Level 1") or alt attribute for map areas
                    name_from_title_attr = element.get_attribute("data-title") or element.get_attribute("title") or element.get_attribute("alt") or ""
                    name = name_from_title_attr.split(" Seviye")[0].strip() if " Seviye" in name_from_title_attr else name_from_title_attr.strip()
                    if not name: name = f"Bina GID {gid}"


                    level = 0
                    # Level from label layer text or class
                    level_text_from_label_el = element.locator("div.labelLayer")
                    if level_text_from_label_el.is_visible(timeout=50): # Very short timeout, may not exist
                        level_text_from_label = level_text_from_label_el.inner_text().strip()
                        level = self._get_safe_int_from_text(level_text_from_label, name + " Seviyesi", default_value=0) # default 0
                    
                    # Level from class (e.g. levelX)
                    class_attr = element.get_attribute("class") or ""
                    level_class_match = re.search(r'\blevel(\d+)\b', class_attr)
                    if level_class_match:
                        level_from_class = int(level_class_match.group(1))
                        if level_from_class > level: level = level_from_class
                    
                    if level == 0 and "Seviye" in name_from_title_attr: # Try parsing from title if other methods yield 0
                        level_match_title = re.search(r'Seviye\s*(\d+)', name_from_title_attr)
                        if level_match_title: level = int(level_match_title.group(1))


                    # location_id from class (aXX) or from 'href' (build.php?id=XX) for map areas
                    location_id = None
                    loc_id_match_class = re.search(r'\ba(\d+)\b', class_attr) # e.g. "a19" for slot 19
                    if loc_id_match_class:
                        location_id = loc_id_match_class.group(1)
                    
                    if not location_id:
                        href_attr = element.get_attribute("href")
                        if href_attr:
                            loc_id_match_href = re.search(r'[?&]id=(\d+)', href_attr)
                            if loc_id_match_href:
                                location_id = loc_id_match_href.group(1)
                    
                    if not location_id:
                        logger.warning(f"{name} (GID: {gid}) için konum ID'si bulunamadı, atlanıyor. Class: '{class_attr}', Title: '{name_from_title_attr}'")
                        continue
                    
                    # is_under_construction = "underConstruction" in class_attr (removed from Building dataclass)

                    buildings.append(Building(name=name, level=level, gid=gid, location_id=location_id))
                    logger.debug(f"Köy merkezi binası eklendi: Name='{name}', Level={level}, LocID='{location_id}', GID='{gid}'")

                except Exception as building_e:
                    logger.debug(f"Köy binası slotu (index {i}, GID: {element.get_attribute('data-gid') if element else 'N/A'}) ayrıştırılamadı: {building_e}")
            
            logger.info(f"Toplam {len(buildings) - initial_building_count} köy merkezi binası çekildi. Genel toplam: {len(buildings)}")
            return buildings
        except Exception as e:
            logger.error(f"Binaları köy {target_village_id} için çekerken genel hata: {e}", exc_info=True)
            return []

    def get_building_queue(self, village_id: Optional[str] = None) -> List[Building]:
        if not self.page or not self._is_active:
            logger.error("Sayfa mevcut değil veya aktif oturum yok. İnşaat kuyruğu çekilemiyor."); return []
        
        target_village_id = village_id or self.current_village_id
        if not target_village_id: logger.error("İnşaat kuyruğu için köy ID'si belirlenemedi."); return []

        queue: List[Building] = []
        try:
            self.navigate_to_village(target_village_id) # Ensures on dorf1
            if not self.page.url.split('?')[0].endswith("dorf1.php"):
                 logger.error(f"İnşaat kuyruğu için dorf1.php (köy {target_village_id}) navigasyonu başarısız.")
                 return []
            else: # Reload to get latest queue
                self.page.reload(wait_until="domcontentloaded")


            # Selector for building queue items. Needs verification.
            queue_elements = self.page.locator("div.buildingList ul li")
            count = queue_elements.count()
            logger.info(f"{count} inşaat kuyruğu öğesi bulundu (köy {target_village_id}).")

            for i in range(count):
                element = queue_elements.nth(i)
                try:
                    name_level_text_element = element.locator("div.name")
                    timer_span = element.locator("span.timer[data-value], span.timer[value]") # Look for data-value or value

                    if not name_level_text_element.is_visible(timeout=200) or not timer_span.is_visible(timeout=200):
                        logger.debug(f"Kuyruk öğesi {i} için isim/zamanlayıcı bulunamadı veya görünür değil.")
                        continue

                    name_level_text = name_level_text_element.inner_text().strip()
                    
                    duration_seconds_str = timer_span.get_attribute("data-value") or timer_span.get_attribute("value")
                    duration_seconds = self._get_safe_int_from_text(duration_seconds_str, "Kuyruk Süresi")

                    match = re.match(r'(.+?)\s+Seviye\s+(\d+)', name_level_text, re.IGNORECASE)
                    if match:
                        name = match.group(1).strip()
                        level_being_built = int(match.group(2)) # This is the level it will become
                        queue.append(Building(name=name, level=level_being_built, build_time_remaining=duration_seconds))
                    else:
                        logger.warning(f"Kuyruk öğesi metni anlaşılamadı: '{name_level_text}'")

                except Exception as item_e:
                    logger.warning(f"Kuyruk öğesi (index {i}) ayrıştırılırken hata: {item_e}")
            
            logger.info(f"İnşaat kuyruğu köy {target_village_id} için çekildi: {len(queue)} öğe.")
            return queue
        except Exception as e:
            logger.error(f"İnşaat kuyruğunu köy {target_village_id} için çekerken hata: {e}", exc_info=True)
            return []
    
    def get_troops_in_village(self, village_id: Optional[str] = None) -> List[Troop]:
        if not self.page or not self._is_active:
            logger.error("Sayfa mevcut değil veya aktif oturum yok. Askerler çekilemiyor."); return []

        target_village_id = village_id or self.current_village_id
        if not target_village_id: logger.error("Asker çekmek için köy ID'si belirtilmedi."); return []
        
        troops_list: List[Troop] = []
        try:
            self.navigate_to_village(target_village_id) # Ensures on dorf1
            if not self.page.url.split('?')[0].endswith("dorf1.php"):
                 logger.error(f"Askerler için dorf1.php (köy {target_village_id}) navigasyonu başarısız.")
                 return []
            else: # Reload to get latest troop counts
                self.page.reload(wait_until="domcontentloaded")


            # Selector for troop rows. Needs verification.
            troop_rows = self.page.locator("div#villageInfoboxRightContent table#troops tbody tr, table.troop_details tbody tr") # Common patterns
            count = troop_rows.count()
            logger.info(f"{count} potansiyel asker satırı bulundu (köy {target_village_id}).")

            if count == 0: # No table rows found
                 logger.info(f"Köyde {target_village_id} asker tablosu bulunamadı veya boş.")
                 return []
            
            # Check for "no troops" message if the table itself has a specific class or text
            first_row_text_lc = troop_rows.first.inner_text().lower()
            if "hazır yok" in first_row_text_lc or "no troops" in first_row_text_lc :
                 if count == 1 : # Only one row and it says "no troops"
                    logger.info(f"Köyde {target_village_id} asker bulunmuyor (mesaj: '{first_row_text_lc}').")
                    return []


            for i in range(count):
                row = troop_rows.nth(i)
                try:
                    # td.ico img.unit OR td:first-child img.unit OR .uniticon img
                    img_element = row.locator("td.ico img.unit, td:first-child img.unit, .uniticon img").first
                    # td.num OR td.un OR .troop Gletscher
                    count_element = row.locator("td.num, td.un, .troop").first

                    if img_element.is_visible(timeout=100) and count_element.is_visible(timeout=100):
                        type_name = img_element.get_attribute("alt") or img_element.get_attribute("title")
                        if not type_name:
                            class_attr = img_element.get_attribute("class") or ""
                            match_class_troop = re.search(r'\bu(\d+)\b', class_attr) # e.g. u1, u11, u21 for Romans
                            if match_class_troop: type_name = f"Birim u{match_class_troop.group(1)}"
                        
                        count_str = count_element.inner_text()
                        count_val = self._get_safe_int_from_text(count_str, type_name or f"Asker Satırı {i}")

                        if type_name and count_val > 0:
                            troops_list.append(Troop(type_name=type_name, count=count_val))
                            logger.debug(f"Bulunan asker: {type_name}, Sayı: {count_val}")
                        elif type_name and count_val == 0 and not ("hazır yok" in count_str.lower() or "no troops" in count_str.lower()):
                            logger.debug(f"Asker tipi '{type_name}' mevcut ama sayısı 0.")
                        elif not type_name and count_val > 0 :
                             logger.warning(f"Asker sayısı {count_val} bulundu ama tipi belirlenemedi. Satır: {row.inner_text()}")


                except Exception as troop_row_e:
                    logger.debug(f"Asker satırı (index {i}) ayrıştırılırken hata: {troop_row_e}. Satır içeriği: {row.inner_text(timeout=100) if row else 'N/A'}")
            
            logger.info(f"Köy {target_village_id} için {len(troops_list)} farklı tipte, toplam {sum(t.count for t in troops_list)} asker çekildi.")
            return troops_list
        except Exception as e:
            logger.error(f"Askerleri köy {target_village_id} için çekerken hata: {e}", exc_info=True)
            return []

    # --- Placeholder/Warning stubs for methods requiring HTML analysis ---
    # These need to be implemented based on the actual HTML of build.php, hero.php, rally point etc.

    def start_building_upgrade(self, building_name: str, location_id: str, village_id: Optional[str] = None) -> bool:
        if not self.page or not self._is_active: logger.error("Sayfa mevcut değil. Yükseltme başlatılamıyor."); return False
        target_village_id = village_id or self.current_village_id
        if not target_village_id: logger.error("Yükseltme için köy ID'si belirtilmedi."); return False
        
        logger.warning(f"start_building_upgrade: '{building_name}' (Konum: {location_id}) köy {target_village_id}. Bu fonksiyonun build.php HTML'ine göre revize edilmesi gerekiyor.")
        # 1. Navigate to village (dorf1 or dorf2)
        self.navigate_to_village(target_village_id)
        # 2. Click on the building slot to go to build.php?id=location_id
        try:
            # Try dorf1 (resource fields 1-18)
            if int(location_id) <= 18:
                self.page.goto(f"{self.server_url}/dorf1.php?newdid={target_village_id}", wait_until="domcontentloaded")
                build_link_selector = f"a.resourceField[data-aid='{location_id}']" # Example
            # Try dorf2 (village center 19+)
            else:
                self.page.goto(f"{self.server_url}/dorf2.php?newdid={target_village_id}", wait_until="domcontentloaded")
                build_link_selector = f"div.buildingSlot.a{location_id} a, map#map2 area[href*='id={location_id}']" # Examples

            slot_link = self.page.locator(build_link_selector).first
            if slot_link.is_visible():
                slot_link.click()
                self.page.wait_for_url(f"**/build.php**id={location_id}**", timeout=15000)
                logger.info(f"build.php?id={location_id} sayfasına gidildi.")
            else:
                logger.warning(f"build.php için '{building_name}' (Konum {location_id}) linki bulunamadı.")
                # Fallback: directly try to go to build.php
                self.page.goto(f"{self.server_url}/build.php?newdid={target_village_id}&id={location_id}", wait_until="domcontentloaded")


            # 3. On build.php, find and click the upgrade button
            # Common selectors: button.green.build, div.build_button button, input.green.button-upgrade
            upgrade_button = self.page.locator("button.green.build:not([disabled]), div.build_button button:not([disabled]), input.green.button-upgrade:not([disabled])").first
            if upgrade_button.is_visible():
                logger.info(f"'{building_name}' için yükseltme butonu bulundu, tıklanıyor...")
                upgrade_button.click()
                self.page.wait_for_load_state("domcontentloaded") # Wait for action to complete
                # Check for success (e.g., redirect back to dorf1/dorf2, or message)
                if "dorf1.php" in self.page.url or "dorf2.php" in self.page.url:
                    logger.info(f"'{building_name}' yükseltmesi başarıyla başlatıldı (dorf1/dorf2 yönlendirmesi).")
                    return True
                # More specific success/error messages can be checked here
                build_error = self.page.locator("div.error, span.error, div.errorMessage")
                if build_error.count() > 0 and build_error.first.is_visible():
                    logger.warning(f"'{building_name}' yükseltilemedi. Hata mesajı: {build_error.first.inner_text()}")
                    return False
                logger.info(f"'{building_name}' yükseltme talebi gönderildi, durum belirsiz (dorf1/2 yönlendirmesi yok).")
                return True # Optimistic, assumes it worked if no immediate error
            else:
                logger.warning(f"'{building_name}' için yükseltme butonu bulunamadı veya pasif. Kaynak/önkoşul eksik olabilir.")
                return False

        except Exception as e:
            logger.error(f"'{building_name}' yükseltilirken hata: {e}", exc_info=True)
            return False


    def train_troops(self, village_id: str, troop_type: str, amount: int) -> bool:
        # troop_name_map and troop_counts from original seems to be for multiple troops.
        # This is simplified to one troop type and amount, BotEngine should loop if multiple.
        if not self.page or not self._is_active: logger.error("Sayfa mevcut değil."); return False
        logger.warning(f"train_troops: {amount} x '{troop_type}' köy {village_id}. Bu fonksiyonun Kışla/Ahır vb. HTML'ine göre revize edilmesi gerekiyor.")
        
        # This requires knowing the GID of the training building (Barracks, Stable, Workshop)
        # and mapping troop_type to the game's internal troop ID (e.g., u1, u2 for Romans)
        # For simplicity, this is a very basic placeholder.
        # Example: For Legionnaire (u1) in Barracks (gid 19)
        # 1. Navigate to Barracks: build.php?newdid={village_id}&gid=19
        # 2. Find input field for troop (e.g., input[name='t1'])
        # 3. Fill amount
        # 4. Click train button
        # This is highly game-version specific.
        # self.page.goto(f"{self.server_url}/build.php?newdid={village_id}&gid=TRAINING_BUILDING_GID")
        # self.page.fill(f"input[name='{troop_input_field_name}']", str(amount))
        # self.page.click("button#s1_ok, button.green.train") # Example train button
        # logger.info(f"{amount} adet '{troop_type}' eğitimi başlatıldı (simüle).")
        # return True
        logger.error("train_troops fonksiyonu tam olarak implemente edilmedi.")
        return False

    def get_hero_status(self) -> Optional[HeroStatus]:
        if not self.page or not self._is_active:
            logger.error("Sayfa mevcut değil veya aktif oturum yok. Kahraman durumu çekilemiyor."); return None
        try:
            logger.info("Kahraman durumu çekiliyor (hero.php)...")
            self.page.goto(f"{self.server_url}/hero", wait_until="domcontentloaded", timeout=20000)

            # Health: Often a percentage in a title or a specific element text
            # Example selectors, these WILL need verification for your Travian version
            health_el = self.page.locator("div.health svg title, .heroDashboardGeneral #health tooltip, .healthPath title").first
            health = 0
            if health_el.is_visible(timeout=1000):
                health_text = health_el.inner_text() # e.g., "Health: 100%"
                health_match = re.search(r'(\d+)%', health_text)
                if health_match: health = int(health_match.group(1))
            
            # Experience: Similar to health
            exp_el = self.page.locator("div.experience svg title, .heroDashboardGeneral #experience tooltip, .experiencePath title").first
            experience = 0
            if exp_el.is_visible(timeout=1000):
                exp_text = exp_el.inner_text() # e.g., "Experience: 50%"
                exp_match = re.search(r'(\d+)%', exp_text)
                if exp_match: experience = int(exp_match.group(1))

            # Status: "Home", "Adventure", "Reinforcing Village X", "Attacking Y"
            # This is usually a text element.
            status_el = self.page.locator(".heroStatus div.text, .heroStatusMessage, #heroStatus div.movements div.text").first # Highly variable
            status = "Bilinmiyor"
            if status_el.is_visible(timeout=1000):
                 status_text_raw = status_el.inner_text().lower()
                 if "evde" in status_text_raw or "köyde" in status_text_raw or "home" in status_text_raw: status = "Evde"
                 elif "macera" in status_text_raw or "adventure" in status_text_raw: status = "Macerada"
                 elif "yolda" in status_text_raw or "returning" in status_text_raw or "outgoing" in status_text_raw: status = "Yolda"
                 else: status = status_el.inner_text().strip() # Use raw if not recognized

            # Adventure available: Often a button with a count or a specific class
            # The log showed 'a#button683f34ec7308a' before, which is too specific.
            # General adventure button often on dorf1 or hero page.
            # Check for a link to /hero/adventures or a specific adventure button.
            adventure_button_dorf1_sidebar = self.page.locator("div#sidebarBoxHero div.layoutButton.adventureWhite") # Typical dorf1 sidebar
            adventure_link_hero_page = self.page.locator("a[href*='hero/adventures'], .adventureListAvailable .adventureSlot") # On hero page

            adventure_available = False
            if adventure_button_dorf1_sidebar.is_visible(timeout=500) and not adventure_button_dorf1_sidebar.get_attribute("class",timeout=100).contains("disable"):
                adventure_available = True
            elif self.page.url.endswith("/hero"): # If on hero page, check specific links
                 if adventure_link_hero_page.count() > 0 : adventure_available = True

            # If still not found, try the specific ID from logs as a last resort (but it's bad practice)
            # adventure_button_specific_id = self.page.locator("a#button683f34ec7308a")
            # if adventure_button_specific_id.is_visible(timeout=100):
            #     if self._get_safe_int_from_text(adventure_button_specific_id.locator("div.content").inner_text()) > 0:
            #         adventure_available = True

            hero = HeroStatus(health=health, experience=experience, status=status, adventure_available=adventure_available)
            logger.info(f"Kahraman durumu: Sağlık={hero.health}%, Deneyim={hero.experience}%, Durum='{hero.status}', Macera Mevcut={hero.adventure_available}")
            return hero
        except Exception as e:
            logger.error(f"Kahraman durumunu çekerken hata: {e}", exc_info=True)
            return None


    def send_hero_to_adventure(self) -> bool:
        if not self.page or not self._is_active: logger.error("Sayfa mevcut değil."); return False
        logger.warning("send_hero_to_adventure fonksiyonu hero/adventures HTML'ine göre revize edilmelidir.")
        try:
            # Go to adventure list page
            self.page.goto(f"{self.server_url}/hero/adventures", wait_until="domcontentloaded", timeout=20000)
            
            # Look for an available adventure and click its "Start adventure" button
            # Selector needs to be specific to your Travian version's HTML for adventure entries
            # Common patterns: .adventureListAvailable .adventureSlot a.gotoAdventure, .list-entry.adventure .start-adventure-button
            start_adventure_button = self.page.locator("td.goTo div a, .adventure.enabled .goToAdventureLink, .list-entry.adventure a[href*='startAdventure']").first
            
            if start_adventure_button.is_visible(timeout=3000):
                logger.info("Uygun bir macera ('Maceraya Başla' butonu) bulundu, tıklanıyor...")
                start_adventure_button.click()
                # Some versions have an immediate confirmation page, some don't.
                # Wait for navigation or confirmation.
                try:
                    self.page.wait_for_url(f"**{self.server_url}/hero/adventures**", timeout=10000, wait_until="domcontentloaded") # Wait for it to go or come back
                except PlaywrightError: # Timeout likely means it went to hero overview or dorf1
                    logger.info("Maceraya gönderme sonrası /hero/adventures'a yönlendirme beklenmedi veya zaman aşımına uğradı. Durum kontrol ediliyor...")

                # Check if hero status changed or if back on adventure list with one less adventure
                # This is a simple check; more robust would be to see if hero is "On adventure"
                if "heroStatus" in self.page.content().lower() and ("yolda" in self.page.content().lower() or "macerada" in self.page.content().lower()):
                     logger.info("Kahraman maceraya gönderildi (durum metni değişti).")
                     return True
                
                # Fallback: look for a confirmation button on a new page if no direct status change detected
                confirm_button = self.page.locator("button.green:has-text('Onayla'), button:has-text('Maceraya başla'), #startAdventureForm button[type='submit']").first
                if confirm_button.is_visible(timeout=2000):
                    logger.info("Macera onay butonu bulundu, tıklanıyor...")
                    confirm_button.click()
                    self.page.wait_for_load_state("domcontentloaded")
                    logger.info("Kahraman maceraya gönderildi (onay sonrası).")
                    return True

                logger.warning("Kahraman maceraya gönderildi ancak başarı durumu tam olarak doğrulanamadı.")
                return True # Optimistic
            else:
                logger.info("Gönderilecek uygun macera butonu bulunamadı (td.goTo div a vb.).")
                return False
        except Exception as e:
            logger.error(f"Kahramanı maceraya gönderirken hata: {e}", exc_info=True)
            return False

    def send_raid(self, source_village_id: str, target_coords: Dict[str, int], troops_to_send: Dict[str, int]) -> bool:
        # troops_to_send is {'TroopTypeName': count}, e.g. {'Lejyoner': 10}
        # This needs a mapping from TroopTypeName to the game's input field names (e.g. 't1', 't2')
        if not self.page or not self._is_active: logger.error("Sayfa mevcut değil."); return False
        logger.warning(f"send_raid: Köy {source_village_id} -> {target_coords} ile {troops_to_send}. Bu fonksiyonun Askeri Üs HTML'ine göre revize edilmesi gerekiyor.")

        # Example mapping (ROMANS). This should be part of game config or tribe specific.
        troop_name_to_input_field = {
            "Lejyoner": "t1", "Praetorian": "t2", "Imperian": "t3",
            "Equites Legati": "t4", "Equites Imperatoris": "t5", "Equites Caesaris": "t6",
            # ... other troops and other tribes
        }

        try:
            # 1. Navigate to Rally Point (gid=16) of the source_village_id
            self.page.goto(f"{self.server_url}/build.php?newdid={source_village_id}&gid=16", wait_until="domcontentloaded", timeout=20000)

            # 2. Fill target coordinates
            self.page.fill("input#xCoordInput, input.coordinates.x", str(target_coords["x"]))
            self.page.fill("input#yCoordInput, input.coordinates.y", str(target_coords["y"]))

            # 3. Fill troop amounts
            for troop_name, count in troops_to_send.items():
                input_field_name = troop_name_to_input_field.get(troop_name)
                if not input_field_name:
                    logger.warning(f"Asker tipi '{troop_name}' için giriş alanı adı bilinmiyor. Atlanıyor.")
                    continue
                self.page.fill(f"input[name='{input_field_name}']", str(count))
                logger.debug(f"'{troop_name}' için {count} adet girildi ({input_field_name}).")
            
            # 4. Select raid type (2 for normal raid, 3 for attack - check value on your server)
            # raid_option_button = self.page.locator("input[type='radio'][name='c'][value='3']") # Value 3 for Normal Raid
            # if not raid_option_button.is_checked(): raid_option_button.check()
            # For Travian Kingdoms / Legends, it's often buttons
            raid_button_selector = "label[for='raidTypeAttack'], input#raidTypeAttack" # Adjust if it's "Reinforcement" or "Normal Raid" etc.
            self.page.click(raid_button_selector) # Assuming "Attack" / Normal Raid
            logger.debug(f"Yağma tipi seçildi (saldırı).")


            # 5. Click "Send" or "OK" button
            send_button_rallypoint = self.page.locator("button#btn_ok, button.green.sendTroops").first
            if send_button_rallypoint.is_visible():
                send_button_rallypoint.click()
                self.page.wait_for_load_state("domcontentloaded") # Wait for confirmation page
            else:
                logger.error("Askeri Üs'te 'Gönder' butonu bulunamadı.")
                return False

            # 6. On confirmation page, click final "Send" / "Confirm"
            confirm_send_button = self.page.locator("button#troopSendConfirm button, button.green.troopSendConfirm").first # Travian Kingdoms style
            if confirm_send_button.is_visible():
                confirm_send_button.click()
                self.page.wait_for_load_state("domcontentloaded")
                logger.info(f"Yağma {target_coords} hedefine başarıyla gönderildi (onay sonrası).")
                return True
            else: # Maybe no confirmation page or different selector
                # If already redirected back to rally point or dorf1, assume success
                if "build.php?gid=16" in self.page.url or "dorf1.php" in self.page.url:
                     logger.info(f"Yağma {target_coords} hedefine gönderildi (onay sayfası atlandı veya hemen yönlendirildi).")
                     return True
                logger.warning("Yağma gönderme onay butonu bulunamadı. Gönderme durumu belirsiz.")
                return False # Or true if optimistic

        except Exception as e:
            logger.error(f"Yağma gönderirken hata ({source_village_id} -> {target_coords}): {e}", exc_info=True)
            return False

    def get_nearby_village_info(self, center_village_id: str, radius: int = 7) -> List[Dict[str, Any]]:
        # This function requires navigating to the map and parsing it.
        # Map parsing is complex and highly dependent on the game's JavaScript and HTML.
        # The original code had a placeholder; this should be properly implemented.
        logger.warning(f"`get_nearby_village_info` köy {center_village_id} (yarıçap: {radius}) için SİMÜLE EDİLMİŞ veri döndürüyor. Gerçek implementasyon gerekiyor.")
        
        # Placeholder implementation - returns dummy data
        simulated_targets = []
        if not self.page or not self._is_active:
            logger.error("Harita verisi çekilemiyor: Sayfa yok veya aktif oturum yok.")
            return []

        # Basic idea:
        # 1. Go to map: self.page.goto(f"{self.server_url}/karte.php") or similar
        # 2. Find center village coordinates (or use known ones if current_village_id is center_village_id)
        # 3. Iterate over map tiles in radius (requires complex JS interaction or parsing map data JSON if available)
        # 4. For each tile, get info (village name, player, population, type: village/oasis)
        # This is a SKELETON, actual implementation is much more involved.
        # try:
        #    # Get current village coords if it's the center
        #    # This is a simplification. Real map parsing is needed.
        #    logger.info(f"Simulating nearby villages for village ID {center_village_id}")
        #    # ... (actual map parsing logic would go here) ...
        # except Exception as e:
        #    logger.error(f"Yakındaki köy bilgileri çekilirken (simülasyon aşamasında hata): {e}")

        # Example simulated data:
        for i in range(random.randint(3, 8)):
            sim_type = random.choice(["village", "oasis_wood", "oasis_clay", "oasis_iron", "oasis_crop", "oasis_wood_crop"])
            sim_pop = random.randint(2, 300) if sim_type == "village" else 0
            sim_player_status = "inaktif" if sim_pop < 50 and sim_type == "village" else "bilinmiyor"
            if "oasis" in sim_type : sim_player_status = "vaha"

            simulated_targets.append({
                "name": f"Simüle Köy/Vaha {i+1}",
                "coords": {"x": random.randint(-radius, radius), "y": random.randint(-radius, radius)}, # Relative to center
                "population": sim_pop,
                "type": sim_type,
                "player_status": sim_player_status,
                "defense_hint": "bilinmiyor" if sim_type == "village" else "natar" if "oasis" in sim_type else "zayıf"
            })
        logger.info(f"Simülasyon: {len(simulated_targets)} adet yakındaki köy/vaha bilgisi oluşturuldu.")
        return simulated_targets
