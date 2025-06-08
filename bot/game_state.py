# --- travian_bot_project/bot/game_state.py ---
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Any

@dataclass
class Building:
    """Bir köydeki tek bir binayı temsil eder."""
    name: str
    level: int
    gid: Optional[str] = None  # Travian'daki genel bina ID'si
    location_id: Optional[str] = None  # Köy içindeki konumu
    build_time_remaining: Optional[int] = 0  # Saniye cinsinden

@dataclass
class Troop:
    """Belirli bir türdeki asker birliğini temsil eder."""
    type_name: str  # Örneğin, "Lejyoner"
    count: int

@dataclass
class Village:
    """Bir oyuncu köyünü temsil eder."""
    name: str
    id: str  # Köyün benzersiz ID'si (genellikle URL'den alınır)
    coordinates: Optional[Dict[str, int]] = None  # {"x": 10, "y": -5}
    resources: Dict[str, int] = field(default_factory=lambda: {"wood": 0, "clay": 0, "iron": 0, "crop": 0})
    storage_capacity: Dict[str, int] = field(default_factory=lambda: {"warehouse": 800, "granary": 800})
    production_rates: Dict[str, int] = field(default_factory=lambda: {"wood": 10, "clay": 10, "iron": 10, "crop": 5})
    buildings: List[Building] = field(default_factory=list)
    troops_home: List[Troop] = field(default_factory=list)
    building_queue: List[Building] = field(default_factory=list)  # Devam eden veya sıradaki inşaatlar [cite: 216]
    population: int = 0
    crop_consumption: int = 0

    def can_afford(self, cost: Dict[str, int]) -> bool:
        """Belirli bir maliyeti karşılayıp karşılayamayacağını kontrol eder."""
        for resource, amount in cost.items():
            if self.resources.get(resource, 0) < amount:
                return False
        return True

    def get_building_by_location_id(self, location_id: str) -> Optional[Building]:
        """Belirli bir konum ID'sine sahip binayı döndürür."""
        for building in self.buildings:
            if building.location_id == location_id:
                return building
        return None

@dataclass
class HeroStatus:
    """Kahramanın durumunu temsil eder."""
    health: int = 100
    experience: int = 0
    status: str = "Evde"  # Örneğin, "Evde", "Macerada", "Yolda" [cite: 217]
    current_location: Optional[str] = None
    adventure_available: bool = False

@dataclass
class PlayerAccount:
    """Oyuncunun tüm Travian hesabını temsil eder."""
    username: str
    villages: List[Village] = field(default_factory=list)
    hero: HeroStatus = field(default_factory=HeroStatus)
    culture_points: int = 0 
