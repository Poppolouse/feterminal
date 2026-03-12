# feterminal

GTK4 + VTE tabanli, Adwaita gorunum kullanan ve kisayollari hem arayuzden hem `shortcuts.json` dosyasindan degistirilebilen hafif bir terminal uygulamasi.

## Calistirma

```bash
python3 /var/home/poppolouse/feterminal/feterminal.py
```

## Varsayilan kisayollar

- `Ctrl+C`: kopyala
- `Ctrl+V`: metin yapistir
- `Ctrl+Shift+C`: aktif komuta `Ctrl+C` gonder
- `Ctrl+Shift+V`: panodaki gorseli PNG olarak `/tmp` altina kaydedip yolunu yapistir
- `Ctrl+Shift+R`: terminali resetle
- `F5`: `shortcuts.json` dosyasini yeniden yukle
- `Ctrl+,`: ayarlari ac
- `Ctrl+Shift+Q`: pencereyi kapat

## Kisayol degistirme

Uygulama menusu icinden `Preferences` acilabilir veya `Ctrl+,` kullanilabilir. Istersen yine `/var/home/poppolouse/feterminal/shortcuts.json` dosyasini elle de duzenleyebilirsin. Ornek:

```json
{
  "copy": ["<Ctrl>c"],
  "send_interrupt": ["<Ctrl><Shift>c"],
  "paste": ["<Ctrl>v"],
  "paste_image": ["<Ctrl><Shift>v"],
  "open_preferences": ["<Ctrl>comma"]
}
```

Not: terminalde "gorselin kendisini" yapistirmak evrensel bir davranis degil. Bu uygulama `Ctrl+Shift+V` ile gorseli dosyaya cevirip yolunu komut satirina birakir.

## Masaustu kisayolu

Uygulama dosyasi:

- `/var/home/poppolouse/feterminal/feterminal.desktop`
