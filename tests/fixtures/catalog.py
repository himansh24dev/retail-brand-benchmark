"""Product catalogue backing the fixture set."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class CatalogItem:
    sku: str
    title: str
    product_type: str
    oem: str | None
    brand: str
    base_price_usd: float
    specs: dict[str, str] = field(default_factory=dict)
    badge_alt: str | None = None
    has_brand_media: bool = True
    has_oem_media: bool = True
    promo: str | None = None


BADGE_RATE = {"intel": 0.86, "amd": 0.71, "qualcomm": 0.42, "apple": 0.93}

BRAND_MEDIA_RATE = {"intel": 0.78, "amd": 0.63, "qualcomm": 0.31, "apple": 0.88}

_N = "notebook"
_D = "desktop"
_W = "workstation"
_T = "tablet"
_C = "cpu"
_G = "gpu"


CATALOG: list[CatalogItem] = [
    CatalogItem("N82E16834156001", "Lenovo Legion Pro 7i Gaming Laptop Intel Core i9-14900HX NVIDIA GeForce RTX 4080 32GB DDR5 1TB SSD 16\" WQXGA 240Hz", _N, "lenovo", "intel", 2499.99,
                {"Processor": "Intel Core i9-14900HX", "Graphics": "NVIDIA GeForce RTX 4080 12GB", "Memory": "32GB DDR5", "Storage": "1TB PCIe SSD", "Screen Size": "16 inch", "Operating System": "Windows 11 Home"},
                badge_alt="Intel Core i9"),
    CatalogItem("N82E16834156002", "ASUS ROG Strix G16 Gaming Laptop Intel Core i7-13650HX GeForce RTX 4070 16GB 1TB 16\" 165Hz", _N, "asus", "intel", 1599.99,
                {"Processor": "Intel Core i7-13650HX", "Graphics": "NVIDIA GeForce RTX 4070 8GB", "Memory": "16GB DDR5", "Storage": "1TB PCIe SSD", "Screen Size": "16 inch"},
                badge_alt="Intel Core i7"),
    CatalogItem("N82E16834156003", "Dell XPS 14 9440 Intel Core Ultra 7 155H 32GB 1TB OLED Touch Creator Laptop", _N, "dell", "intel", 1899.99,
                {"Processor": "Intel Core Ultra 7 155H", "Graphics": "Intel Arc Graphics", "Memory": "32GB LPDDR5x", "Storage": "1TB SSD", "Screen Size": "14.5 inch"},
                badge_alt="Intel Core Ultra 7"),
    CatalogItem("N82E16834156004", "HP Victus 15 Gaming Laptop Intel Core i5-13420H AMD Radeon RX 6550M 8GB 512GB", _N, "hp", "intel", 749.99,
                {"Processor": "Intel Core i5-13420H", "Graphics": "AMD Radeon RX 6550M 4GB", "Memory": "8GB DDR4", "Storage": "512GB SSD"},
                badge_alt="Intel Core i5"),
    CatalogItem("N82E16834156005", "MSI Katana 15 Gaming Laptop Intel Core i7-13620H RTX 4060 16GB 1TB M.2 NVMe SSD 144Hz", _N, "msi", "intel", 1199.99,
                {"Processor": "Intel Core i7-13620H", "Graphics": "NVIDIA GeForce RTX 4060 8GB", "Memory": "16GB DDR5", "Storage": "1TB M.2 NVMe SSD"},
                badge_alt="Intel Core i7"),
    CatalogItem("N82E16834156006", "Acer Predator Helios Neo 16 Intel Core i7-14650HX RTX 4060 16GB 512GB", _N, "acer", "intel", 1349.99,
                {"Processor": "Intel Core i7-14650HX", "Graphics": "NVIDIA GeForce RTX 4060 8GB", "Memory": "16GB DDR5", "Storage": "512GB SSD"},
                badge_alt="Intel Core i7"),
    CatalogItem("N82E16834156007", "Lenovo ThinkPad P1 Gen 7 Mobile Workstation Intel Core Ultra 9 185H vPro RTX 3000 Ada 64GB", _W, "lenovo", "intel", 3299.99,
                {"Processor": "Intel Core Ultra 9 185H", "Graphics": "NVIDIA RTX 3000 Ada 8GB", "Memory": "64GB DDR5", "Storage": "2TB SSD"},
                badge_alt="Intel vPro"),
    CatalogItem("N82E16834156008", "Dell Precision 5690 Mobile Workstation Intel Core Ultra 7 165H 32GB RTX 2000 Ada", _W, "dell", "intel", 2799.99,
                {"Processor": "Intel Core Ultra 7 165H", "Graphics": "NVIDIA RTX 2000 Ada", "Memory": "32GB DDR5", "Storage": "1TB SSD"},
                badge_alt="Intel Core Ultra 7"),

    CatalogItem("N82E16834156101", "Lenovo Legion 5 Gaming Laptop AMD Ryzen 7 7735HS NVIDIA GeForce RTX 4060 16GB 512GB 15.6\" 144Hz", _N, "lenovo", "amd", 1099.99,
                {"Processor": "AMD Ryzen 7 7735HS", "Graphics": "NVIDIA GeForce RTX 4060 8GB", "Memory": "16GB DDR5", "Storage": "512GB SSD"},
                badge_alt="AMD Ryzen 7"),
    CatalogItem("N82E16834156102", "ASUS ROG Zephyrus G14 AMD Ryzen AI 9 HX 370 RTX 4070 32GB 1TB OLED 120Hz", _N, "asus", "amd", 1999.99,
                {"Processor": "AMD Ryzen AI 9 HX 370", "Graphics": "NVIDIA GeForce RTX 4070 8GB", "Memory": "32GB LPDDR5X", "Storage": "1TB SSD"},
                badge_alt="AMD Ryzen AI"),
    CatalogItem("N82E16834156103", "Alienware m18 R2 Gaming Laptop AMD Ryzen 9 7945HX3D RTX 4090 32GB 2TB", _N, "dell", "amd", 3499.99,
                {"Processor": "AMD Ryzen 9 7945HX3D", "Graphics": "NVIDIA GeForce RTX 4090 16GB", "Memory": "32GB DDR5", "Storage": "2TB SSD"},
                badge_alt="AMD Ryzen 9"),
    CatalogItem("N82E16834156104", "ASUS TUF Gaming A15 AMD Ryzen 7 7435HS RTX 4060 16GB 512GB 144Hz", _N, "asus", "amd", 949.99,
                {"Processor": "AMD Ryzen 7 7435HS", "Graphics": "NVIDIA GeForce RTX 4060 8GB", "Memory": "16GB DDR5", "Storage": "512GB SSD"},
                badge_alt="AMD Ryzen 7"),
    CatalogItem("N82E16834156105", "HP OMEN 16 Gaming Laptop AMD Ryzen 5 7640HS Radeon RX 7600M XT 16GB 1TB", _N, "hp", "amd", 1049.99,
                {"Processor": "AMD Ryzen 5 7640HS", "Graphics": "AMD Radeon RX 7600M XT 8GB", "Memory": "16GB DDR5", "Storage": "1TB SSD"},
                badge_alt="AMD Ryzen 5"),
    CatalogItem("N82E16834156106", "Lenovo LOQ 15 Gaming Laptop AMD Ryzen 5 7235HS RTX 3050 8GB 512GB", _N, "lenovo", "amd", 699.99,
                {"Processor": "AMD Ryzen 5 7235HS", "Graphics": "NVIDIA GeForce RTX 3050 6GB", "Memory": "8GB DDR5", "Storage": "512GB SSD"},
                badge_alt=None),
    CatalogItem("N82E16834156107", "MSI Cyborg 15 AMD Ryzen 7 7735HS RTX 4050 16GB 512GB Gaming Notebook", _N, "msi", "amd", 899.99,
                {"Processor": "AMD Ryzen 7 7735HS", "Graphics": "NVIDIA GeForce RTX 4050 6GB", "Memory": "16GB DDR5", "Storage": "512GB SSD"},
                badge_alt="AMD Ryzen 7"),

    CatalogItem("N82E16834156201", "ASUS Zenbook A14 Snapdragon X Elite X1E-78-100 32GB 1TB OLED Copilot+ PC", _N, "asus", "qualcomm", 1399.99,
                {"Processor": "Qualcomm Snapdragon X Elite X1E-78-100", "Graphics": "Qualcomm Adreno GPU", "Memory": "32GB LPDDR5X", "Storage": "1TB SSD"},
                badge_alt="Snapdragon"),
    CatalogItem("N82E16834156202", "HP OmniBook X 14 Snapdragon X Plus X1P-64-100 16GB 512GB Copilot+ PC", _N, "hp", "qualcomm", 1049.99,
                {"Processor": "Qualcomm Snapdragon X Plus", "Memory": "16GB LPDDR5X", "Storage": "512GB SSD"},
                badge_alt=None),
    CatalogItem("N82E16834156203", "Lenovo ThinkBook 16 Snapdragon X Elite 16GB 512GB Copilot+ Laptop", _N, "lenovo", "qualcomm", 1199.99,
                {"Processor": "Qualcomm Snapdragon X Elite", "Memory": "16GB LPDDR5X", "Storage": "512GB SSD"},
                badge_alt=None),
    CatalogItem("N82E16834156204", "Dell Inspiron 14 Plus Snapdragon X Plus 16GB 1TB Copilot+ PC", _N, "dell", "qualcomm", 999.99,
                {"Processor": "Qualcomm Snapdragon X Plus X1P-42-100", "Memory": "16GB LPDDR5X", "Storage": "1TB SSD"},
                badge_alt="Snapdragon"),
    CatalogItem("N82E16834156205", "Acer Swift 14 AI Snapdragon X Elite 32GB 1TB Copilot+ Touch", _N, "acer", "qualcomm", 1299.99,
                {"Processor": "Qualcomm Snapdragon X Elite", "Memory": "32GB LPDDR5X", "Storage": "1TB SSD"},
                badge_alt=None),

    CatalogItem("N82E16834156301", "Apple MacBook Pro 14\" M4 Pro chip 24GB Unified Memory 512GB SSD Space Black", _N, "apple", "apple", 1999.99,
                {"Processor": "Apple M4 Pro chip", "Graphics": "Apple 16-core GPU", "Memory": "24GB Unified Memory", "Storage": "512GB SSD"},
                badge_alt="Apple Silicon"),
    CatalogItem("N82E16834156302", "Apple MacBook Air 15\" M3 chip 16GB 512GB SSD Midnight", _N, "apple", "apple", 1499.99,
                {"Processor": "Apple M3 chip", "Graphics": "Apple 10-core GPU", "Memory": "16GB Unified Memory", "Storage": "512GB SSD"},
                badge_alt="Apple Silicon"),
    CatalogItem("N82E16834156303", "Apple MacBook Pro 16\" M4 Max chip 48GB 1TB SSD", _N, "apple", "apple", 3999.99,
                {"Processor": "Apple M4 Max chip", "Memory": "48GB Unified Memory", "Storage": "1TB SSD"},
                badge_alt="Apple Silicon"),
    CatalogItem("N82E16834156304", "Apple Mac mini M4 chip 16GB 256GB SSD Desktop Computer", _D, "apple", "apple", 599.99,
                {"Processor": "Apple M4 chip", "Memory": "16GB Unified Memory", "Storage": "256GB SSD"},
                badge_alt="Apple Silicon"),
    CatalogItem("N82E16834156305", "Apple iPad Pro 13\" M4 chip 256GB Wi-Fi Space Black", _T, "apple", "apple", 1299.99,
                {"Processor": "Apple M4 chip", "Memory": "8GB", "Storage": "256GB"},
                badge_alt="Apple Silicon"),
    CatalogItem("N82E16834156306", "Apple Mac Studio M2 Ultra 64GB 1TB SSD Workstation", _W, "apple", "apple", 3999.99,
                {"Processor": "Apple M2 Ultra chip", "Memory": "64GB Unified Memory", "Storage": "1TB SSD"},
                badge_alt="Apple Silicon"),

    CatalogItem("N82E16883156401", "ASUS ROG Strix G16CH Gaming Desktop Intel Core i7-14700F RTX 4070 32GB 1TB", _D, "asus", "intel", 1799.99,
                {"Processor": "Intel Core i7-14700F", "Graphics": "NVIDIA GeForce RTX 4070 12GB", "Memory": "32GB DDR5", "Storage": "1TB SSD"},
                badge_alt="Intel Core i7"),
    CatalogItem("N82E16883156402", "Alienware Aurora R16 Gaming Desktop Intel Core i9-14900KF RTX 4090 32GB 2TB", _D, "dell", "intel", 3799.99,
                {"Processor": "Intel Core i9-14900KF", "Graphics": "NVIDIA GeForce RTX 4090 24GB", "Memory": "32GB DDR5", "Storage": "2TB SSD"},
                badge_alt="Intel Core i9"),
    CatalogItem("N82E16883156403", "HP OMEN 45L Gaming Desktop AMD Ryzen 9 7950X RTX 4080 SUPER 32GB 2TB", _D, "hp", "amd", 2899.99,
                {"Processor": "AMD Ryzen 9 7950X", "Graphics": "NVIDIA GeForce RTX 4080 SUPER 16GB", "Memory": "32GB DDR5", "Storage": "2TB SSD"},
                badge_alt="AMD Ryzen 9"),
    CatalogItem("N82E16883156404", "Lenovo Legion Tower 5 Gaming Desktop AMD Ryzen 7 8700G Radeon RX 7700 XT 16GB", _D, "lenovo", "amd", 1399.99,
                {"Processor": "AMD Ryzen 7 8700G", "Graphics": "AMD Radeon RX 7700 XT 12GB", "Memory": "16GB DDR5", "Storage": "1TB SSD"},
                badge_alt="AMD Ryzen 7"),
    CatalogItem("N82E16883156405", "MSI Aegis R2 Gaming Desktop Intel Core i5-14400F RTX 4060 Ti 16GB 1TB", _D, "msi", "intel", 1199.99,
                {"Processor": "Intel Core i5-14400F", "Graphics": "NVIDIA GeForce RTX 4060 Ti 8GB", "Memory": "16GB DDR5", "Storage": "1TB SSD"},
                badge_alt=None),
    CatalogItem("N82E16883156406", "Acer Predator Orion 3000 Intel Core i7-14700F RTX 4060 Ti 16GB 1TB Gaming PC", _D, "acer", "intel", 1499.99,
                {"Processor": "Intel Core i7-14700F", "Graphics": "NVIDIA GeForce RTX 4060 Ti 8GB", "Memory": "16GB DDR5", "Storage": "1TB SSD"},
                badge_alt="Intel Core i7"),

    CatalogItem("N82E16819113741", "AMD Ryzen 7 9800X3D 8-Core 16-Thread Unlocked Desktop Processor", _C, None, "amd", 479.00,
                {"Processor": "AMD Ryzen 7 9800X3D", "Cores": "8", "Brand": "AMD"},
                badge_alt="AMD Ryzen"),
    CatalogItem("N82E16819113742", "AMD Ryzen 9 9950X 16-Core 32-Thread Desktop Processor", _C, None, "amd", 649.00,
                {"Processor": "AMD Ryzen 9 9950X", "Cores": "16", "Brand": "AMD"},
                badge_alt="AMD Ryzen"),
    CatalogItem("N82E16819118456", "Intel Core Ultra 9 285K 24-Core Desktop Processor LGA1851", _C, None, "intel", 589.00,
                {"Processor": "Intel Core Ultra 9 285K", "Cores": "24", "Brand": "Intel"},
                badge_alt="Intel Core Ultra"),
    CatalogItem("N82E16819118457", "Intel Core i5-14600K 14-Core Desktop Processor LGA1700", _C, None, "intel", 279.00,
                {"Processor": "Intel Core i5-14600K", "Cores": "14", "Brand": "Intel"},
                badge_alt="Intel Core i5"),
    CatalogItem("N82E16819113743", "AMD Ryzen 5 7600X 6-Core Desktop Processor", _C, None, "amd", 199.00,
                {"Processor": "AMD Ryzen 5 7600X", "Cores": "6", "Brand": "AMD"},
                badge_alt=None),

    CatalogItem("N82E16814137812", "GIGABYTE GeForce RTX 4070 SUPER WINDFORCE OC 12G Graphics Card", _G, None, "nvidia", 599.99,
                {"Graphics": "NVIDIA GeForce RTX 4070 SUPER", "Graphics Memory": "12GB GDDR6X", "Brand": "GIGABYTE"}),
    CatalogItem("N82E16814137813", "ASUS TUF Gaming GeForce RTX 4060 Ti OC 8GB GDDR6 Graphics Card", _G, None, "nvidia", 419.99,
                {"Graphics": "NVIDIA GeForce RTX 4060 Ti", "Graphics Memory": "8GB GDDR6", "Brand": "ASUS"}),
    CatalogItem("N82E16814202456", "Sapphire PULSE AMD Radeon RX 7800 XT 16GB GDDR6 Graphics Card", _G, None, "amd", 479.99,
                {"Graphics": "AMD Radeon RX 7800 XT", "Graphics Memory": "16GB GDDR6", "Brand": "Sapphire"},
                badge_alt="AMD Radeon"),
    CatalogItem("N82E16814202457", "XFX Speedster MERC 310 AMD Radeon RX 7900 XTX 24GB Graphics Card", _G, None, "amd", 899.99,
                {"Graphics": "AMD Radeon RX 7900 XTX", "Graphics Memory": "24GB GDDR6", "Brand": "XFX"},
                badge_alt="AMD Radeon"),
    CatalogItem("N82E16814137814", "Intel Arc A770 Limited Edition 16GB GDDR6 Graphics Card", _G, None, "intel", 329.99,
                {"Graphics": "Intel Arc A770", "Graphics Memory": "16GB GDDR6", "Brand": "Intel"},
                badge_alt="Intel Arc"),

    CatalogItem("N82E16834156501", "Microsoft Surface Pro 11 Snapdragon X Elite 16GB 512GB Copilot+ 2-in-1", _T, None, "qualcomm", 1499.99,
                {"Processor": "Qualcomm Snapdragon X Elite", "Memory": "16GB", "Storage": "512GB SSD"},
                badge_alt="Snapdragon"),
    CatalogItem("N82E16834156502", "Lenovo Tab Extreme MediaTek Dimensity 9000 12GB 256GB Android Tablet", _T, "lenovo", "mediatek", 949.99,
                {"Processor": "MediaTek Dimensity 9000", "Memory": "12GB", "Storage": "256GB"}),

    CatalogItem("N82E16834156901", "Gaming Laptop Backpack 17.3 inch Water Resistant Travel Bag", _N, None, "other", 49.99,
                {"Brand": "Generic", "Color": "Black"}, has_brand_media=False, has_oem_media=False),
    CatalogItem("N82E16834156902", "Refurbished Business Laptop 15.6\" 8GB 256GB SSD Windows 11", _N, None, "other", 299.99,
                {"Memory": "8GB", "Storage": "256GB SSD"}, has_brand_media=False, has_oem_media=False),
]


ML_CATALOG: list[CatalogItem] = [
    CatalogItem("MLB3421001", "Notebook Gamer Lenovo Legion 5 AMD Ryzen 7 7735HS RTX 4060 16GB 512GB SSD 15.6\" 144Hz", _N, "lenovo", "amd", 8499.90,
                {"Processador": "AMD Ryzen 7 7735HS", "Placa de vídeo": "NVIDIA GeForce RTX 4060", "Memória RAM": "16GB DDR5", "Capacidade de armazenamento": "512GB SSD", "Tamanho da tela": "15.6 polegadas"},
                badge_alt="AMD Ryzen 7"),
    CatalogItem("MLB3421002", "Notebook Gamer Acer Nitro V15 Intel Core i5-13420H RTX 4050 16GB 512GB SSD", _N, "acer", "intel", 5799.90,
                {"Processador": "Intel Core i5-13420H", "Placa de vídeo": "NVIDIA GeForce RTX 4050", "Memória RAM": "16GB DDR5", "Capacidade de armazenamento": "512GB SSD"},
                badge_alt="Intel Core i5"),
    CatalogItem("MLB3421003", "Notebook Gamer Dell G15 Intel Core i7-13650HX RTX 4060 16GB 1TB SSD 165Hz", _N, "dell", "intel", 7999.90,
                {"Processador": "Intel Core i7-13650HX", "Placa de vídeo": "NVIDIA GeForce RTX 4060", "Memória RAM": "16GB DDR5", "Capacidade de armazenamento": "1TB SSD"},
                badge_alt="Intel Core i7"),
    CatalogItem("MLB3421004", "Notebook Gamer ASUS ROG Strix G16 Intel Core i9-14900HX RTX 4070 32GB 1TB", _N, "asus", "intel", 13499.90,
                {"Processador": "Intel Core i9-14900HX", "Placa de vídeo": "NVIDIA GeForce RTX 4070", "Memória RAM": "32GB DDR5", "Capacidade de armazenamento": "1TB SSD"},
                badge_alt="Intel Core i9"),
    CatalogItem("MLB3421005", "Notebook Gamer Lenovo LOQ AMD Ryzen 5 7235HS RTX 3050 8GB 512GB SSD", _N, "lenovo", "amd", 4299.90,
                {"Processador": "AMD Ryzen 5 7235HS", "Placa de vídeo": "NVIDIA GeForce RTX 3050", "Memória RAM": "8GB DDR5", "Capacidade de armazenamento": "512GB SSD"},
                badge_alt=None),
    CatalogItem("MLB3421006", "Notebook Gamer MSI Katana 15 Intel Core i7-13620H RTX 4060 16GB 1TB M.2 NVMe", _N, "msi", "intel", 8199.90,
                {"Processador": "Intel Core i7-13620H", "Placa de vídeo": "NVIDIA GeForce RTX 4060", "Memória RAM": "16GB DDR5", "Capacidade de armazenamento": "1TB M.2 NVMe"},
                badge_alt="Intel Core i7"),
    CatalogItem("MLB3421007", "Notebook Gamer ASUS TUF Gaming A15 AMD Ryzen 7 7435HS RTX 4060 16GB 512GB", _N, "asus", "amd", 6799.90,
                {"Processador": "AMD Ryzen 7 7435HS", "Placa de vídeo": "NVIDIA GeForce RTX 4060", "Memória RAM": "16GB DDR5", "Capacidade de armazenamento": "512GB SSD"},
                badge_alt="AMD Ryzen 7"),
    CatalogItem("MLB3421008", "Notebook Gamer HP Victus 15 AMD Ryzen 5 7640HS RTX 2050 16GB 512GB SSD", _N, "hp", "amd", 4899.90,
                {"Processador": "AMD Ryzen 5 7640HS", "Placa de vídeo": "NVIDIA GeForce RTX 2050", "Memória RAM": "16GB DDR5", "Capacidade de armazenamento": "512GB SSD"},
                badge_alt=None),
    CatalogItem("MLB3421009", "Notebook Apple MacBook Air 13\" Chip M3 8GB 256GB SSD Meia-noite", _N, "apple", "apple", 9999.00,
                {"Processador": "Apple M3 chip", "Memória RAM": "8GB", "Capacidade de armazenamento": "256GB SSD"},
                badge_alt="Apple Silicon"),
    CatalogItem("MLB3421010", "Notebook Apple MacBook Pro 14\" Chip M4 Pro 24GB 512GB SSD", _N, "apple", "apple", 18999.00,
                {"Processador": "Apple M4 Pro chip", "Memória RAM": "24GB", "Capacidade de armazenamento": "512GB SSD"},
                badge_alt="Apple Silicon"),
    CatalogItem("MLB3421011", "Notebook Samsung Galaxy Book4 Edge Snapdragon X Elite 16GB 512GB", _N, None, "qualcomm", 8999.00,
                {"Processador": "Qualcomm Snapdragon X Elite", "Memória RAM": "16GB", "Capacidade de armazenamento": "512GB SSD"},
                badge_alt=None),
    CatalogItem("MLB3421012", "Notebook Gamer Acer Predator Helios Neo 16 Intel Core i7-14650HX RTX 4060 16GB", _N, "acer", "intel", 9499.90,
                {"Processador": "Intel Core i7-14650HX", "Placa de vídeo": "NVIDIA GeForce RTX 4060", "Memória RAM": "16GB DDR5"},
                badge_alt="Intel Core i7"),

    CatalogItem("MLB3422001", "PC Gamer Completo AMD Ryzen 5 5600G 16GB SSD 480GB Radeon Vega 7", _D, None, "amd", 2499.90,
                {"Processador": "AMD Ryzen 5 5600G", "Memória RAM": "16GB DDR4", "Capacidade de armazenamento": "480GB SSD"},
                badge_alt="AMD Ryzen 5"),
    CatalogItem("MLB3422002", "Computador Gamer Intel Core i5-12400F RTX 3060 16GB SSD 1TB", _D, None, "intel", 4799.90,
                {"Processador": "Intel Core i5-12400F", "Placa de vídeo": "NVIDIA GeForce RTX 3060", "Memória RAM": "16GB DDR4"},
                badge_alt="Intel Core i5"),
    CatalogItem("MLB3422003", "PC Gamer Lenovo Legion Tower 5 AMD Ryzen 7 8700G RTX 4060 Ti 16GB 1TB", _D, "lenovo", "amd", 8999.90,
                {"Processador": "AMD Ryzen 7 8700G", "Placa de vídeo": "NVIDIA GeForce RTX 4060 Ti", "Memória RAM": "16GB DDR5"},
                badge_alt="AMD Ryzen 7"),
    CatalogItem("MLB3422004", "Computador Gamer Dell Alienware Aurora R16 Intel Core i7-14700F RTX 4070 32GB", _D, "dell", "intel", 16999.90,
                {"Processador": "Intel Core i7-14700F", "Placa de vídeo": "NVIDIA GeForce RTX 4070", "Memória RAM": "32GB DDR5"},
                badge_alt="Intel Core i7"),
    CatalogItem("MLB3422005", "Apple Mac mini Chip M4 16GB 256GB SSD", _D, "apple", "apple", 6499.00,
                {"Processador": "Apple M4 chip", "Memória RAM": "16GB", "Capacidade de armazenamento": "256GB SSD"},
                badge_alt="Apple Silicon"),

    CatalogItem("MLB3423001", "Processador AMD Ryzen 5 5600X 3.7GHz 6-Core AM4 Box", _C, None, "amd", 899.90,
                {"Processador": "AMD Ryzen 5 5600X", "Marca": "AMD"},
                badge_alt="AMD Ryzen"),
    CatalogItem("MLB3423002", "Processador Intel Core i5-14600K 14-Core LGA1700", _C, None, "intel", 1699.90,
                {"Processador": "Intel Core i5-14600K", "Marca": "Intel"},
                badge_alt="Intel Core i5"),
    CatalogItem("MLB3423003", "Processador AMD Ryzen 7 9800X3D 8-Core AM5", _C, None, "amd", 2899.90,
                {"Processador": "AMD Ryzen 7 9800X3D", "Marca": "AMD"},
                badge_alt=None),
    CatalogItem("MLB3424001", "Placa de Video Gigabyte GeForce RTX 4060 Ti 8GB GDDR6", _G, None, "nvidia", 2999.90,
                {"Placa de vídeo": "NVIDIA GeForce RTX 4060 Ti", "Memória de vídeo": "8GB GDDR6", "Marca": "Gigabyte"}),
    CatalogItem("MLB3424002", "Placa de Video Sapphire AMD Radeon RX 7800 XT 16GB GDDR6", _G, None, "amd", 3899.90,
                {"Placa de vídeo": "AMD Radeon RX 7800 XT", "Memória de vídeo": "16GB GDDR6", "Marca": "Sapphire"},
                badge_alt="AMD Radeon"),

    CatalogItem("MLB3425001", "Apple iPad Pro 13\" Chip M4 256GB Wi-Fi", _T, "apple", "apple", 12499.00,
                {"Processador": "Apple M4 chip", "Capacidade de armazenamento": "256GB"},
                badge_alt="Apple Silicon"),
    CatalogItem("MLB3425002", "Tablet Samsung Galaxy Tab S9 Snapdragon 8 Gen 2 12GB 256GB", _T, None, "qualcomm", 5499.90,
                {"Processador": "Qualcomm Snapdragon 8 Gen 2", "Memória RAM": "12GB"},
                badge_alt="Snapdragon"),

    CatalogItem("MLB3426001", "Workstation Dell Precision 5690 Intel Core Ultra 7 165H 32GB RTX 2000 Ada", _W, "dell", "intel", 24999.90,
                {"Processador": "Intel Core Ultra 7 165H", "Memória RAM": "32GB DDR5"},
                badge_alt="Intel Core Ultra 7"),

    CatalogItem("MLB3429001", "Mochila para Notebook Gamer 17 polegadas Impermeável", _N, None, "other", 189.90,
                {"Marca": "Genérica"}, has_brand_media=False, has_oem_media=False),
]


def catalog_for(platform_key: str) -> list[CatalogItem]:
    return ML_CATALOG if platform_key == "mercadolibre_br" else CATALOG
