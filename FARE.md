# FARE.md — Gamepower Icarus (258A:0027) Tam Kapsamlı Handoff & Yeni Plan

> **Hedef:** Yeni ajan için sıfır varsayımla eksiksiz donanım, protokol, pinout, codex ve REA haritası; geçmiş oturumların özeti ve köklü çözüm yol haritası.

---

## 1. Durum Özeti & Mevcut Kilitlenme

- **Fiziksel Belirti:**
  - Sol, sağ, orta tık ve kaydırma tekeri **%100 kusursuz çalışıyor** (Interrupt IN EP 0x81 üzerinden `01 <buttons> ...` paketleri Linux çekirdeğine akıyor).
  - İmleç hareketi ($\Delta X, \Delta Y$) **sıfır hareket üretiyor** (EP 0x81'den gelen hareket baytları daima `00 00 00 00`).
  - **Sensör Işığı (Kamera Altında):** PixArt PMW3325 sensörünün altındaki optik ışık **saniyede 3-4 kez (3-4 Hz) düzenli yanıp sönüyor (pulsing)**. Bu durum sensörün enerjilendiğini, ancak yüzey odaklayamayıp `Rest2 / Rest3` uyku modunda takıldığını kanıtlar.
- **Geçmiş Olay Zinciri:**
  - 29 Ekim 23:25 commit'inde (`6428681`) fare tamamen çalışıyordu.
  - Kullanıcı harici NTFS `SSS` USB sürücüsünü sisteme tanıtmak için `/etc/udisks2/mount_options.conf`, `launch-obsidian-vault` ve USB udiskie ayarlarını değiştirdi; xHCI denetleyicisinde 31 saniyelik zaman aşımı / reset olayları yaşandı.
  - Eve dönüp fare takıldığında hareket tamamen kesilmiş bulundu.

---

## 2. Donanım Mimarisi & Veriyolu Haritası

```
+-----------------------------------------------------------------------------------+
|                        Linux USB Host (xHCI Denetleyici)                          |
|   /dev/hidraw0 (EP 0x81: Mouse Input)        /dev/hidraw1 (EP 0x00: Vendor/Cfg)   |
+-----------------------------------+-----------------------------------------------+
                                    | USB 2.0 Full-Speed (12 Mbps), VID:PID = 258A:0027
+-----------------------------------v-----------------------------------------------+
|                       Sinowealth 8051-Core USB MCU                                |
|                       (SH68F83 / BY8832 Firmware)                                 |
|                                                                                   |
|  [Dahili Flash Bellek Haritası]                                                   |
|  • Profil 1 Blok 1 (Cmd 0x11): 520 Bayt Config (DPI, RGB, Polling, Sensör Reg)    |
|  • Profil 1 Blok 2 (Cmd 0x12): 520 Bayt Buton Tablosu (K1..K20)                  |
|  • Profil 2 Blok 1 (Cmd 0x21): 520 Bayt Config                                   |
|  • Profil 2 Blok 2 (Cmd 0x22): 520 Bayt Buton Tablosu                            |
|  • Makro Blokları  (Cmd 0x30): 520 Bayt Onboard Makro Belleği                     |
+-----------------------------------+-----------------------------------------------+
                                    | Dahili Donanımsal 4-Telli SPI Veriyolu:
                                    | NCS, SCLK, SDIO/MOSI, MISO, MOTION_INT
+-----------------------------------v-----------------------------------------------+
|                     PixArt PMW3325DB-TWV1 Optik Sensör                            |
|  • Çözünürlük: 200 - 5000 DPI (Native 100 DPI adımlarla)                         |
|  • İzleme Hızı: 100 IPS, 20G Hızlanma, 850nm Kızılötesi/Kırmızı LED              |
|  • Durum: MCU tarafından başlatılmayı bekleyen Rest2 modunda (3-4 Hz puls).      |
+-----------------------------------------------------------------------------------+
```

---

## 3. Protokol & Codex Haritası (Tersine Mühendislik Çıktısı)

Windows sürücüsü (`OemDrv.exe` & `Lowerdev.dll`) REA analizinde `CDrv8948` ve `CDev8948` sınıfları üzerinden kesinleşen komut haritası:

### A. Komut Kanalı (Feature Report `0x05`, Boyut: 6 Bayt)
`SetFeature(handle, [0x05, cmd, data0, data1, data2, data3], 6)`

| Opcode (`cmd`) | Bayt 1 (`data0`) | İşlev | Yanıt / Açıklama |
| :--- | :--- | :--- | :--- |
| `0x01` | `0x00` | **GetPSD** | `GetFeature(0x04)` ile `V901` (4 bayt versiyon) döner. |
| `0x02` | `0x00` | **GetActiveProfile** | Aktif profili sorgular (`1`, `2` veya `3`). |
| `0x02` | `0x01` / `0x02` | **SetActiveProfile** | Donanım aktif profilini `1` veya `2` yapar. |
| `0x11` | `0x00` | **ReadBlock P1 B1** | Profil 1 Config bloğunu (520 bayt) okuma moduna alır. |
| `0x12` | `0x00` | **ReadBlock P1 B2** | Profil 1 Buton bloğunu (520 bayt) okuma moduna alır. |
| `0x21` | `0x00` | **ReadBlock P2 B1** | Profil 2 Config bloğunu okuma moduna alır. |
| `0x22` | `0x00` | **ReadBlock P2 B2** | Profil 2 Buton bloğunu okuma moduna alır. |
| `0x13` | `0x00` | **ReadMacro** | Makro veri bloğunu okuma moduna alır. |

> [!CRITICAL]
> **Windows sürücüsünde hiçbir gizli sensör başlatma/uyandırma komutu YOKTUR.**
> `SendCmd` (`0x413180`) fonksiyonu `OemDrv.exe` içinde sadece yukarıdaki 4 işlev tarafından çağrılır. Sensör başlatması tamamen MCU'nun flash bellekteki konfigürasyon bloğunu SPI üzerinden PMW3325'e basmasıyla gerçekleşir.

---

### B. Veri & Flash Bellek Kanalı (Feature Report `0x04`, Boyut: 520 Bayt)
`SetFeature(handle, buffer_520b, 520)`

#### 1. Config Bloğu (Blok 1 — Opcodes `0x11` / `0x21`)
- **Yazma Koruması / Magic Baytı:** `buf[3] = 0x7B` olmak zorundadır (`OemDrv.exe @ 0x413730`). Bu bayt olmadan MCU yazmayı sessizce reddeder.
- **Bayt Haritası:**
  - `buf[0]`: Report ID = `0x04`
  - `buf[1]`: Blok Opcode (`0x11` = P1, `0x21` = P2)
  - `buf[2]`: `0x00`
  - `buf[3]`: **Magic = `0x7B`** (Yazmada zorunlu; okumada `0x00` döner)
  - `buf[8]`: Profil ID / Mod
  - `buf[9]`: Sensör Tanımlayıcı Maskesi (`buf[9] & 0x3F == 0x0B` -> PMW3325 `0x3325`)
  - `buf[10]`: Polling Rate (`0x01`=125Hz, `0x02`=250Hz, `0x03`=500Hz, `0x04`=1000Hz)
  - `buf[11]`: `(active_dpi_index << 4) | total_dpi_count`
  - `buf[12]`: Devre dışı DPI kademe bitmask'i
  - `buf[13..20]`: 8 DPI kademesinin donanım indeksleri (`0x03`..`0x3B` -> 400..10000 DPI)
  - `buf[29..52]`: 8 DPI kademesinin RGB renkleri (3 bayt $\times$ 8)
  - `buf[53]`: RGB Efekti (`0`=Streaming, `1`=Steady, `2`=Breathing, `4`=Neon, `9`=Off)
  - `buf[54]`: RGB Hızı (`0x00`..`0x02`)
  - `buf[55]`: RGB Parlaklığı (`0x00`..`0x04`)
  - `buf[56]`: RGB Yönü (`0`=Saat yönü, `1`=Ters)
  - `buf[57..59]`: Statik/Tek Renk RGB değeri
  - `buf[104..132]`: **PMW3325 Doğrudan Sensör/SPI Kayıtları (KRİTİK):**
    - `buf[104]`: Shutter alt bayt
    - `buf[120..121]`: Shutter threshold (`0x0000` = Fabrika P1, `0x03fa` = P2)
    - `buf[123]`: Lift-Off Algılama Modu (`0x00` = P1, `0x02` = P2)
    - `buf[129]`: Lift-Off Distance (`0x01` = High 3mm, `0x00` = Low 2mm)
    - `buf[130..131]`: Sensör Fabrika Kalibrasyon Sabitleri (`0x01 0x00` = P1, `0x44 0xf0` = P2)

#### 2. Buton Bloğu (Blok 2 — Opcodes `0x12` / `0x22`)
- **Yazma Koruması / Magic Baytı:** `buf[3] = 0x50` olmak zorundadır (`OemDrv.exe @ 0x4137e0`).
- **Bayt Haritası:**
  - `buf[0]`: Report ID = `0x04`
  - `buf[1]`: Blok Opcode (`0x12` = P1, `0x22` = P2)
  - `buf[3]`: **Magic = `0x50`**
  - `buf[8..87]`: 20 Buton Eşleme Yuvası (Her buton 4 bayt: `[Type, Data0, Data1, Data2]`):
    - `0x11`: Fare Tıklaması (`Data0`: 1=Sol, 2=Sağ, 4=Orta, 8=Geri, 16=İleri)
    - `0x21`: Klavye Tuşu (`Data1`: HID Keycode)
    - `0x22`: Multimedya / Web (`Data0`: 1=Önceki, 2=Sonraki, 4=Durdur, 8=Oynat/Duraklat, 16=Sessiz, 32=Ses+, 64=Ses-)
    - `0x33`: Seri Ateş / Multi-click (`Data0`: Tekrar sayısı, `Data1`: Gecikme ms)
    - `0x41`: DPI Değiştirici (`Data0`: 1=DPI+, 2=DPI-, 3=DPI Döngüsü, 4=Sniper Kilidi)
    - `0x50`: Donanımsal Anahtarlar (`Data0`: 1=Profil Değiştir, 2=Işık Aç/Kapat, 3=Mod Değiştir)
    - `0x70`: Makro Tetikleyici (`Data0`: Makro ID, `Data1`: Döngü Modu)

---

### C. Girdi Kanalı (Interrupt IN `EP 0x81`, 7 Bayt)
- Paket Düzeni: `[0x01, buttons_mask, dx_low, dx_high, dy_low, dy_high, wheel]`
- `buttons_mask`: Bit 0 = Sol, Bit 1 = Sağ, Bit 2 = Orta, Bit 3 = Geri, Bit 4 = İleri.
- `dx`, `dy`: 16-bit signed integer (Two's complement, Little-Endian).

---

## 4. Kullanılacak Beceriler (Skills) & Eklentiler

Yeni ajan bu görevi icra ederken şu araçları önceliklendirmelidir:

1. `reverse-engineer-anything` (REA):
   - Windows ikilisi (`/home/hp/Work/MOUSE/extracted/app/OemDrv.exe`) ve `Lowerdev.dll` disassembly analizleri için `objdump`, `read_bytes` ve RTTI taraması.
2. `systematic-debugging`:
   - Donanım / çekirdek / sensör arızalarını tahmin yürütmeden, hipotez-kanıt döngüsüyle ayırma.
3. `investigate-first`:
   - Kod değiştirmeden önce çekirdek xHCI, USB bus güç durumları ve SPI paket kanıtlarını toplama.
4. `karpathy-guidelines` & `RULE[user_global]`:
   - Değişiklikler cerrahi olmalı.
   - Dosya satır sınırları: `icarus/*.py` kaynak kodları daima $\le 400$ satır kalacak.
   - Sıfır dış kütüphane bağımlılığı (yalnızca standart Python 3: `fcntl`, `os`, `struct`, `argparse`).
   - Durum değiştiren işlemler öncesi kullanıcı onayı (`başla`).

---

## 5. Çözüm Hipotezleri & Köklü Eylem Planı

### Hipotez 1: xHCI / USB Bus Güç Düşüşü & Askıda Kalan Durum (En Yüksek Öncelik)
- **Olay:** SSS diski kilitlenmesi sonrası xHCI resetlendi. Laptop bataryada (`power-saver` modunda).
- **Mekanizma:** PMW3325 yüksek akım (20-30mA) çekmek istediğinde bus gerilimi düşüyor veya port askıda kalıyor; tıklar çalışırken optik motor uyanamıyor.
- **Eylem:**
  1. `usbreset /dev/bus/usb/007/002` veya `/sys/bus/usb/devices/7-1/authorized` toggle (`0 -> 1`) ile donanımsal bus reset at.
  2. Laptopu şarja taktırıp AC güçte kontrol et.

### Hipotez 2: MCU Flash / EEPROM "Reset to Factory" Özel Sekansı
- **Mekanizma:** `Cfg.ini` içinde `ptResetBtn=795,631` koordinatında bir "Factory Reset" butonu tanımlı. Sürücü bu butona basıldığında tek bir bloğu değil, MCU'ya sıfırlama komutu gönderiyor olabilir.
- **Eylem:** `OemDrv.exe` içinde `ptResetBtn` veya reset dialogunun tetiklediği fonksiyonu disassemble et (`0x412d00..0x414000` aralığı) ve varsa sıfırlama baytını bul.

### Hipotez 3: MCU SPI Veriyolu Kilitlenmesi & DPI Cycle Uyandırması
- **Mekanizma:** PMW3325, MCU'dan yeni bir DPI konfigürasyonu gelmeden `Rest2` modundan çıkmıyor.
- **Eylem:** Donanıma `0x50` buton komutu veya DPI kademe geçiş simülasyonu göndererek SPI hattına veri akışı zorla başlatılsın.

---

## 6. Doğrulama Kapıları (Gates)

Herhangi bir çözüm sunulmadan önce çalıştırılması gereken zorunlu komutlar:
1. `python3 -m unittest discover tests`: 42 test 0 hata ile geçmeli.
2. `python3 -c "import os, select; fd=os.open('/dev/hidraw0', os.O_RDONLY|os.O_NONBLOCK); ..."`: Fare hareket ettirildiğinde `/dev/hidraw0` üzerinden en az 1 adet non-zero $dx/dy$ paketi yakalanmalı.
3. `wc -l /home/hp/Work/MOUSE/icarusctl/icarus/*.py`: Bütün dosyalar $\le 400$ satır kalmalı.
