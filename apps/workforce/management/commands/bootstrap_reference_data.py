from django.core.management.base import BaseCommand

from apps.workforce.models import Cadre, DocumentType, Location, TrainingInstitution


CADRES = [
    ("Registered Nurse", "nursing"),
    ("Enrolled Nurse", "nursing"),
    ("Midwife", "midwifery"),
    ("Maternal & Child Health Nurse", "nursing"),
    ("Paediatric Nurse", "nursing"),
    ("Mental Health Nurse", "nursing"),
    ("Nurse Aide", "nursing"),
    ("Community Health Worker (CHW)", "chw"),
    ("Medical Doctor / Specialist", "medical"),
    ("Allied Health Professional", "medical"),
]

DOCUMENT_TYPES = [
    "Passport Photo",
    "Academic Transcript / Certificate",
    "Birth Certificate / National ID",
    "Competency Statement (G4/G5/G6)",
    "CV / Resume",
    "Police Clearance",
    "Medical Fitness Certificate",
    "Receipt of Payment",
    "Logbook / Practical Record",
]

INSTITUTIONS = [
    "University of Papua New Guinea (UPNG) – School of Medicine & Health Sciences",
    "Pacific Adventist University – School of Nursing",
    "Divine Word University – School of Nursing & Allied Health",
    "Mendi School of Nursing",
    "Madang Lutheran School of Nursing",
    "Lae School of Nursing",
    "St. Barnabas School of Nursing (Dogura)",
    "Sacred Heart School of Nursing",
    "West New Britain School of Nursing",
    "Bulu CHW Training College",
    "Albinama CHW Training College",
]

PROVINCE_DISTRICTS = {
    "National Capital District": ["Port Moresby"],
    "Central": ["Abau", "Goilala", "Kairuku", "Rigo"],
    "Gulf": ["Kerema", "Kaintiba", "Kikori"],
    "Milne Bay": ["Alotau", "Esa'ala", "Kiriwina-Goodenough", "Samarai-Murua"],
    "Oro (Northern)": ["Popondetta", "Ijivitari", "Sohe"],
    "Southern Highlands": ["Mendi-Munihu", "Imbonggu", "Kagua-Erave", "Nipa-Kutubu"],
    "Hela": ["Tari-Pori", "Koroba-Lake Kopiago", "Komo-Magarima"],
    "Enga": ["Wabag", "Lagaip-Porgera", "Kandep", "Kompiam-Ambum"],
    "Western Highlands": ["Mt Hagen", "Dei", "Tambul-Nebilyer"],
    "Jiwaka": ["Banz", "Anglimp-South Waghi", "Jimi"],
    "Eastern Highlands": ["Goroka", "Daulo", "Henganofi", "Kainantu", "Lufa", "Obura-Wonenara", "Unggai-Bena"],
    "Chimbu (Simbu)": ["Kundiawa", "Chuave", "Gumine", "Karimui-Nomane", "Kerowagi", "Sinasina-Yonggomugl"],
    "Madang": ["Madang", "Bogia", "Rai Coast", "Sumkar", "Usino-Bundi"],
    "Morobe": ["Lae", "Bulolo", "Finschhafen", "Kabwum", "Markham", "Menyamya", "Nawae", "Tewae-Siassi"],
    "East Sepik": ["Wewak", "Ambunti-Dreikikir", "Angoram", "Maprik", "Wosera-Gawi", "Yangoru-Saussia"],
    "West Sepik (Sandaun)": ["Vanimo-Green", "Aitape-Lumi", "Nuku", "Telefomin"],
    "Western (Fly River)": ["Daru", "Middle Fly", "North Fly", "South Fly"],
    "West New Britain": ["Kimbe", "Talasea"],
    "East New Britain": ["Kokopo", "Gazelle", "Pomio", "Rabaul"],
    "New Ireland": ["Kavieng", "Namatanai"],
    "Manus": ["Lorengau"],
    "Bougainville (Autonomous Region)": ["Buka", "Arawa", "Buin"],
}


class Command(BaseCommand):
    help = "Populate Cadre, Location (22 provinces), TrainingInstitution, and DocumentType reference data."

    def handle(self, *args, **options):
        for name, category in CADRES:
            Cadre.objects.update_or_create(name=name, defaults={"category": category})

        for doc_name in DOCUMENT_TYPES:
            DocumentType.objects.get_or_create(name=doc_name)

        for institution in INSTITUTIONS:
            TrainingInstitution.objects.get_or_create(
                name=institution,
                defaults={"type": "Nursing/Health", "is_active": True},
            )

        for province, districts in PROVINCE_DISTRICTS.items():
            for district in districts:
                Location.objects.get_or_create(province=province, district=district, defaults={"ward": ""})

        self.stdout.write(self.style.SUCCESS("Reference data bootstrapped successfully."))
