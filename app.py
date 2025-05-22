from flask import Flask, request, jsonify
import time
import traceback # Hata ayıklama için eklendi
# import math # Bu modül kullanılmıyorsa kaldırılabilir
import uuid # Benzersiz ID üretmek için
import os # Portu ortam değişkeninden almak için EKLENDİ
import logging
import sys # stdout kullanmak için

# --- YENİ EKLENEN IMPORTLAR (YAPAY ZEKA MODELİ İÇİN) ---
import joblib
import pandas as pd
from datetime import datetime
# --- YENİ EKLENEN IMPORTLAR SONU ---

app = Flask(__name__)

# --- LOGLAMA YAPILANDIRMASI (Mevcut kodunuzdan) ---
# Railway üzerinde logların görünmesi için stdout'a yönlendirme ve seviye ayarı
stream_handler = logging.StreamHandler(sys.stdout)
stream_handler.setLevel(logging.INFO)
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s [in %(pathname)s:%(lineno)d]')
stream_handler.setFormatter(formatter)
app.logger.addHandler(stream_handler)
app.logger.setLevel(logging.INFO)
app.logger.info("Flask uygulaması başlatılıyor ve loglama stdout'a INFO seviyesinde yapılandırıldı.")
# --- LOGLAMA YAPILANDIRMASI SONU ---

# --- YAPAY ZEKA MODELİNİ YÜKLEME ---
MODEL_FILENAME = 'parking_demand_model.joblib' # Model dosyasının adı
AI_MODEL = None
try:
    AI_MODEL = joblib.load(MODEL_FILENAME)
    app.logger.info(f"🧠 Yapay zeka modeli ('{MODEL_FILENAME}') başarıyla yüklendi.")
except FileNotFoundError:
    app.logger.error(f"❌ HATA: Yapay zeka modeli ('{MODEL_FILENAME}') bulunamadı. Dinamik fiyatlandırma bu model olmadan çalışmayacak.")
except Exception as e:
    app.logger.error(f"❌ HATA: Yapay zeka modeli ('{MODEL_FILENAME}') yüklenirken bir sorun oluştu: {str(e)}")
    AI_MODEL = None # Hata durumunda modeli None olarak ayarla
# --- YAPAY ZEKA MODELİNİ YÜKLEME SONU ---


# --- Global Değişkenler (Mevcut kodunuzdan) ---
bekleyen_talepler_park_bazli = []
recent_assignments_park_bazli = {}
RECENT_ASSIGNMENT_TIMEOUT = 5
TUM_PARKLAR = ["A", "B", "C", "D"]
zaman_bazli_bekleyen_talepler = []
# --- Global Değişkenler Sonu ---

# --- YARDIMCI FONKSİYONLAR (Park Kilitleri, Öncelik, Sıralama - Mevcut kodunuzdan) ---
def clean_recent_park_assignments():
    global recent_assignments_park_bazli
    now = time.time()
    keys_to_delete = [park for park, timestamp in recent_assignments_park_bazli.items() if now - timestamp > RECENT_ASSIGNMENT_TIMEOUT]
    if keys_to_delete:
        app.logger.info(f"🧹 Zaman aşımı: Şu park kilitleri kaldırılıyor: {keys_to_delete}")
        for key in keys_to_delete:
            if key in recent_assignments_park_bazli:
                del recent_assignments_park_bazli[key]

def calculate_priority_park(istek):
    current = istek.get("current", 0)
    desired = istek.get("desired", 100)
    arrival_time = istek.get("arrival_time")
    departure_time = istek.get("departure_time")
    charge_need_priority = max(0, desired - current)
    urgency_priority = 0
    now = time.time()
    if departure_time and isinstance(departure_time, (int, float)) and departure_time > now:
        time_to_departure = departure_time - now
        urgency_priority = max(0, 5000 - time_to_departure) / 50
    wait_priority = 0
    if arrival_time and isinstance(arrival_time, (int, float)) and arrival_time < now:
        wait_priority = (now - arrival_time) / 300
    total_priority = (charge_need_priority * 1.5) + (urgency_priority * 1.0) + (wait_priority * 0.5)
    return total_priority

def merge_requests(M, N, key_func):
    merging_list = []
    m = len(M)
    n = len(N)
    i, j = 0, 0
    while i < m or j < n:
        if i == m:
            merging_list.append(N[j])
            j += 1
        elif j == n:
            merging_list.append(M[i])
            i += 1
        elif key_func(M[i]) >= key_func(N[j]): # Büyükten küçüğe sıralama için >=
            merging_list.append(M[i])
            i += 1
        else:
            merging_list.append(N[j])
            j += 1
    return merging_list

def supersort_requests(requests_list, key_func):
    n = len(requests_list)
    if n <= 1:
        return requests_list[:] # Listenin bir kopyasını döndür
    # Bu kısım sizin karmaşık sıralama algoritmanız, olduğu gibi bırakıyorum
    # ... (supersort_requests fonksiyonunun geri kalanı sizin kodunuzdaki gibi) ...
    # Önemli: supersort_requests'in key_func'a göre büyükten küçüğe sıraladığından emin olun.
    # Eğer küçükten büyüğe sıralıyorsa ve öncelik büyük olmalıysa, key_func(x) yerine -key_func(x) kullanılabilir
    # ya da merge_requests içindeki karşılaştırma (>=) buna göre ayarlanmalıdır.
    # Mevcut merge_requests >= kullandığı için büyükten küçüğe sıralama yapıyor olmalı.
    forward_selected = []
    backward_selected = []
    remaining_indices = list(range(n))
    forward_indices_to_remove = []
    current_idx_in_fwd = -1
    for idx in remaining_indices:
        priority = key_func(requests_list[idx])
        if current_idx_in_fwd == -1 or priority >= key_func(requests_list[current_idx_in_fwd]):
            forward_selected.append(requests_list[idx])
            forward_indices_to_remove.append(idx)
            current_idx_in_fwd = idx
    remaining_indices = [idx for idx in remaining_indices if idx not in forward_indices_to_remove]
    if remaining_indices:
        backward_indices_to_remove = []
        current_idx_in_bwd = -1
        for idx in reversed(remaining_indices):
            priority = key_func(requests_list[idx])
            if current_idx_in_bwd == -1 or priority >= key_func(requests_list[current_idx_in_bwd]):
                backward_selected.insert(0, requests_list[idx])
                backward_indices_to_remove.append(idx)
                current_idx_in_bwd = idx
        remaining_indices = [idx for idx in remaining_indices if idx not in backward_indices_to_remove]
    remaining_requests = [requests_list[idx] for idx in remaining_indices]
    mid = len(remaining_requests) // 2
    left_sublist = remaining_requests[:mid]
    right_sublist = remaining_requests[mid:]
    sorted_left = supersort_requests(left_sublist, key_func)
    sorted_right = supersort_requests(right_sublist, key_func)
    merged_recursive = merge_requests(sorted_left, sorted_right, key_func)
    merged_selection = merge_requests(forward_selected, backward_selected, key_func)
    final_sorted_list = merge_requests(merged_selection, merged_recursive, key_func)
    return final_sorted_list
# --- YARDIMCI FONKSİYONLAR SONU ---


# --- YAPAY ZEKA TABANLI FİYAT HESAPLAMA FONKSİYONU ---
# Bu değerleri kendi iş mantığınıza ve modelinizin çıktısına göre ayarlayın.
# Modelinizin 'demand_count' tahmin ettiğini varsayıyoruz.
BASE_PRICE_PARKING_AI = 5.0  # TL (Saatlik otopark için taban ücret)
# Modelin tahmin ettiği birim (örn: 'demand_count') başına eklenecek ücret katsayısı
# Bu katsayıyı, modelinizin RMSE değerini ve istediğiniz fiyatlandırma hassasiyetini göz önünde bulundurarak ayarlayın.
# Örneğin, RMSE 5 ise ve her bir talep birimi için 0.10 TL eklemek isterseniz:
PRICE_PER_DEMAND_UNIT_AI = 0.25 # TL (Örneğin, her bir 'demand_count' birimi için 0.25 TL ek ücret)

def calculate_dynamic_price_from_ai(predicted_demand_unit):
    """
    Yapay zeka modelinin tahmin ettiği talep birimine göre dinamik fiyatı hesaplar.
    """
    if not isinstance(predicted_demand_unit, (int, float)):
        app.logger.error(f"💰 Fiyat hesaplama hatası: predicted_demand_unit sayı değil: {predicted_demand_unit}")
        # Hata durumunda varsayılan veya yüksek bir fiyat döndürebilirsiniz.
        return BASE_PRICE_PARKING_AI # Veya bir hata göstergesi fiyat

    if predicted_demand_unit < 0: # Modelin negatif tahmin yapmaması gerekir ama önlem
        app.logger.warning(f"💰 Fiyat hesaplama: Negatif talep birimi ({predicted_demand_unit}) sıfırlandı.")
        predicted_demand_unit = 0

    # Dinamik bileşen: Tahmin edilen talep ne kadar yüksekse, fiyat o kadar artar.
    # Bu kısım sizin fiyatlandırma stratejinize göre daha karmaşık olabilir.
    # Örneğin, talep eşiklerine göre farklı çarpanlar veya sabit ek ücretler kullanabilirsiniz.
    # Örnek: Talep 0-10 arası normal, 10-20 arası %20 fazla, 20+ %50 fazla gibi.
    dynamic_component = predicted_demand_unit * PRICE_PER_DEMAND_UNIT_AI

    total_price = BASE_PRICE_PARKING_AI + dynamic_component
    app.logger.info(f"💰 Fiyat hesaplama: Taban: {BASE_PRICE_PARKING_AI:.2f}, Talep Birimi: {predicted_demand_unit:.2f}, Katsayı: {PRICE_PER_DEMAND_UNIT_AI:.2f}, Dinamik Ek: {dynamic_component:.2f}, Toplam: {total_price:.2f} TL")
    return round(total_price, 2)
# --- YAPAY ZEKA TABANLI FİYAT HESAPLAMA FONKSİYONU SONU ---


# --- Flask Endpoint'leri (Mevcut kodunuzdan) ---
@app.route('/predict', methods=['POST'])
def predict_park_based():
    global bekleyen_talepler_park_bazli
    try:
        data = request.get_json()
        if not data:
            return jsonify({"status": "error", "message": "İstek gövdesi boş veya JSON değil."}), 400
        doluluk = data.get("doluluk", {})
        requests_input = data.get("requests", [])
        if "new_time_request" in data:
            app.logger.warning(f"⚠️ /predict (park-bazlı) endpoint'ine zaman bazlı bir istek geldi gibi görünüyor: {data}")
            return jsonify({"status": "error", "message": "Yanlış endpoint. Zaman bazlı istekler için /predict_time_slot kullanın."}), 400
        app.logger.info(f"📥 /predict (park-bazlı) - Gelen doluluk: {doluluk}")
        app.logger.info(f"📥 /predict (park-bazlı) - Gelen requests_input (Yeni Park Talebi): {requests_input}")
        if not isinstance(requests_input, list):
            return jsonify({"status": "error", "message": "'requests' bir liste olmalı."}), 400
        last_saved_request = None
        yeni_eklenen_sayisi = 0
        if requests_input:
            for yeni_istek in requests_input:
                if not isinstance(yeni_istek, dict): continue
                if 'arrival_time' not in yeni_istek: yeni_istek['arrival_time'] = time.time()
                if 'departure_time' not in yeni_istek: yeni_istek['departure_time'] = time.time() + 7200
                request_timestamp_id = str(time.time()) + str(hash(str(yeni_istek))) + str(hash(yeni_istek.get("parkid",""))) # uuid ile daha iyi olabilir
                yeni_istek['request_id'] = request_timestamp_id
                if not any(r.get('request_id') == yeni_istek['request_id'] for r in bekleyen_talepler_park_bazli):
                    bekleyen_talepler_park_bazli.append(yeni_istek)
                    last_saved_request = yeni_istek
                    yeni_eklenen_sayisi += 1
                    app.logger.info(f"➕ /predict (park-bazlı) - Kuyruğa eklendi: {yeni_istek}")
                else:
                    app.logger.warning(f"⚠️ /predict (park-bazlı) - Tekrarlanan istek atlandı (ID: {yeni_istek.get('request_id')})")
        if yeni_eklenen_sayisi > 0:
            app.logger.info(f"📊 /predict (park-bazlı) - Yeni talep(ler) eklendi, park kuyruğu sıralanıyor...")
            bekleyen_talepler_park_bazli = supersort_requests(bekleyen_talepler_park_bazli, calculate_priority_park)
            app.logger.info(f"📊 /predict (park-bazlı) - Park kuyruğu sıralandı. Güncel: {bekleyen_talepler_park_bazli}")
        is_full = all(doluluk.get(p, 1) == 1 for p in TUM_PARKLAR if p in doluluk)
        if not doluluk and requests_input: # Eğer doluluk bilgisi hiç gelmediyse ve talep varsa, dolu olmadığını varsayalım.
             is_full = False
        if is_full:
            if last_saved_request:
                return jsonify({"status": "full", "message": "Tüm park alanları dolu, talebiniz kuyruğa alındı.", "saved_request": last_saved_request}), 200
            else:
                return jsonify({"status": "full", "message": "Tüm park alanları dolu."}), 200
        else:
            extra_requests = data.get("extra_requests", [])
            uygun_talepler_onerisi = []
            for istek in extra_requests:
                if not isinstance(istek, dict): continue
                park_id = istek.get("parkid")
                if park_id and doluluk.get(park_id, 1) == 0: # 0 boş demekse
                    uygun_talepler_onerisi.append(istek)
            if requests_input and requests_input[0].get("parkid") and doluluk.get(requests_input[0].get("parkid"), 1) == 0:
                if not any(r.get("parkid") == requests_input[0].get("parkid") for r in uygun_talepler_onerisi):
                      uygun_talepler_onerisi.append(requests_input[0])
            if not uygun_talepler_onerisi and not is_full: # Eğer özel bir talep yoksa ve dolu değilse, boş olanları öner
                for park_id_key in TUM_PARKLAR:
                    if doluluk.get(park_id_key, 1) == 0: # 0 boş demekse
                        uygun_talepler_onerisi.append({"parkid": park_id_key, "current":0, "desired":0, "message":"Bu park boş"})
            sirali_uygun_oneriler = supersort_requests(uygun_talepler_onerisi, calculate_priority_park)
            app.logger.info(f"📊 /predict (park-bazlı) - Parklar boş/kısmen boş, öneri listesi: {sirali_uygun_oneriler}")
            return jsonify({"status": "success", "sirali_istekler": sirali_uygun_oneriler})
    except Exception as e:
        app.logger.error(f"❌ /predict (park-bazlı) - Sunucu hatası: {str(e)}")
        app.logger.error(traceback.format_exc())
        return jsonify({"status": "error", "message": f"Sunucu hatası: {str(e)}"}), 500

@app.route('/assign', methods=['POST'])
def assign_park_based_request():
    global bekleyen_talepler_park_bazli, recent_assignments_park_bazli
    clean_recent_park_assignments()
    try:
        data = request.get_json()
        if not data: return jsonify({"status": "error", "message": "İstek gövdesi boş veya JSON değil."}), 400
        doluluk = data.get("doluluk", {})
        app.logger.info(f"🅿️ /assign (park-bazlı) çağrıldı. Gelen doluluk: {doluluk}")
        app.logger.info(f"🅿️ /assign (park-bazlı) - Mevcut Park Kuyruğu: {bekleyen_talepler_park_bazli}")
        app.logger.info(f"🅿️ /assign (park-bazlı) - Aktif Park Kilitleri: {recent_assignments_park_bazli}")
        if not bekleyen_talepler_park_bazli:
            app.logger.info("🅿️ /assign (park-bazlı) - Park kuyruğu boş.")
            return jsonify({"status": "empty", "message": "Park kuyruğu boş."}), 200
        atanacak_talep = None
        index_to_pop = -1
        atanan_park_id = None
        for i, talep in enumerate(bekleyen_talepler_park_bazli):
            istenen_park = talep.get("parkid")
            if istenen_park and doluluk.get(istenen_park, 1) == 0 and istenen_park not in recent_assignments_park_bazli:
                atanacak_talep = talep; index_to_pop = i; atanan_park_id = istenen_park; break
        if not atanacak_talep:
            for park_id_bos_aday in TUM_PARKLAR:
                if doluluk.get(park_id_bos_aday, 1) == 0 and park_id_bos_aday not in recent_assignments_park_bazli:
                    if bekleyen_talepler_park_bazli: # Kuyrukta hala talep varsa
                        atanacak_talep = bekleyen_talepler_park_bazli[0]; index_to_pop = 0; atanan_park_id = park_id_bos_aday; break
        if atanacak_talep and index_to_pop != -1 and atanan_park_id is not None:
            secilen_talep = bekleyen_talepler_park_bazli.pop(index_to_pop)
            app.logger.info(f"🅿️ /assign (park-bazlı) - Atama: Talep {secilen_talep.get('request_id')} -> Park {atanan_park_id}")
            app.logger.info(f"🅿️ /assign (park-bazlı) - Kalan park kuyruğu: {bekleyen_talepler_park_bazli}")
            recent_assignments_park_bazli[atanan_park_id] = time.time()
            app.logger.info(f"🅿️ /assign (park-bazlı) - Park {atanan_park_id} kilitlendi.")
            atanan_bilgisi = {
                "parkid": atanan_park_id, "current": secilen_talep.get("current"),
                "desired": secilen_talep.get("desired"), "arrival_time": secilen_talep.get("arrival_time"),
                "departure_time": secilen_talep.get("departure_time"), "original_parkid": secilen_talep.get("parkid"),
                "request_id": secilen_talep.get("request_id"), "assigned_timestamp": time.time()
            }
            app.logger.info(f"🅿️ /assign (park-bazlı) - Android'e dönülecek: {atanan_bilgisi}")
            return jsonify({"status": "assigned", "assigned": atanan_bilgisi})
        else:
            app.logger.info("🅿️ /assign (park-bazlı) - Uygun park bulunamadı veya kuyrukta uygun talep yok.")
            if all(doluluk.get(p, 1) == 1 for p in TUM_PARKLAR if p in doluluk):
                 return jsonify({"status": "full", "message": "Tüm parklar dolu."}), 200
            else: # Parklar dolu değil ama ya kilitli ya da talep yok/uygun değil
                 return jsonify({"status": "no_spot_available", "message": "Uygun (boş ve kilitsiz) park bulunamadı."}), 200
    except Exception as e:
        app.logger.error(f"❌ /assign (park-bazlı) Hatası: {e}")
        app.logger.error(traceback.format_exc())
        return jsonify({"status": "error", "message": f"Park atama hatası: {str(e)}"}), 500

@app.route('/predict_time_slot', methods=['POST'])
def predict_time_slot():
    global zaman_bazli_bekleyen_talepler
    try:
        data = request.get_json()
        if not data: return jsonify({"status": "error", "message": "İstek gövdesi boş veya JSON değil."}), 400
        new_time_request = data.get("new_time_request")
        app.logger.info(f"🕰️ /predict_time_slot - Gelen yeni zaman talebi: {new_time_request}")
        if not new_time_request or not isinstance(new_time_request, dict):
            return jsonify({"status": "error", "message": "'new_time_request' geçerli bir obje olmalı."}), 400
        required_fields = ["entryTime", "exitTime", "current", "desired"]
        for field in required_fields:
            if field not in new_time_request:
                return jsonify({"status": "error", "message": f"Eksik alan: '{field}' zaman talebinde bulunmalı."}), 400
        new_time_request['request_id'] = str(uuid.uuid4())
        new_time_request['submission_time'] = time.time()
        zaman_bazli_bekleyen_talepler.append(new_time_request)
        app.logger.info(f"➕ /predict_time_slot - Zaman bazlı kuyruğa eklendi (ID: {new_time_request['request_id']}): {new_time_request}")
        app.logger.info(f"📊 /predict_time_slot - Güncel Zaman Bazlı Kuyruk (eleman sayısı: {len(zaman_bazli_bekleyen_talepler)}): {zaman_bazli_bekleyen_talepler}")
        return jsonify({
            "status": "queued", "request_id": new_time_request['request_id'],
            "message": "Zaman bazlı şarj talebiniz kuyruğa alındı."
        }), 200
    except Exception as e:
        app.logger.error(f"❌ /predict_time_slot - Sunucu hatası: {str(e)}")
        app.logger.error(traceback.format_exc())
        return jsonify({"status": "error", "message": f"Zaman talebi işleme hatası: {str(e)}"}), 500

def calculate_priority_time(req): # Zaman bazlı öncelik - Mevcut kodunuzdan
    now = time.time()
    current = req.get("current", 0)
    desired = req.get("desired", 100)
    entry_str = req.get("entryTime", "00:00") # Varsayılan değerler eklendi
    exit_str = req.get("exitTime", "00:00")   # Varsayılan değerler eklendi
    submission_time = req.get("submission_time", now)
    def time_to_minutes(tstr):
        try: h, m = map(int, tstr.split(":")); return h * 60 + m
        except: app.logger.warning(f"⏰ Zaman dönüştürme hatası: '{tstr}'. 0 olarak kabul ediliyor."); return 0
    entry_minutes = time_to_minutes(entry_str)
    exit_minutes = time_to_minutes(exit_str)
    duration = max(1, exit_minutes - entry_minutes) # Süre en az 1 dakika olmalı
    charge_priority = (desired - current) * 1.5
    wait_priority = max(0, (now - submission_time) / 300) # Bekleme süresi (5 dk'da bir puan artar gibi)
    shorter_duration_bonus = max(0, 180 - duration) * 0.5 # Kısa süreli (örn. <3 saat) rezervasyonlara bonus
    return charge_priority + wait_priority + shorter_duration_bonus

@app.route('/assign_queued_time_slot', methods=['POST'])
def assign_queued_time_slot():
    global zaman_bazli_bekleyen_talepler
    try:
        data = request.get_json()
        if not data: return jsonify({"status": "error", "message": "İstek gövdesi boş veya JSON değil."}), 400
        
        app.logger.info(f"🕰️ /assign_queued_time_slot - Çağrıldı. Kuyruk sıralanıyor...")
        zaman_bazli_bekleyen_talepler = supersort_requests(zaman_bazli_bekleyen_talepler, calculate_priority_time)
        app.logger.info(f"🕰️ /assign_queued_time_slot - Sıralı kuyruk (öncelik ve talepler):")
        for r in zaman_bazli_bekleyen_talepler: # Sıralı kuyruğu logla
             app.logger.info(f"  Priority={calculate_priority_time(r):.2f} | Talep: {r.get('request_id')}")

        park_based_reservations = data.get("park_based_reservations", [])
        app.logger.info(f"🕰️ /assign_queued_time_slot - Gelen park bazlı rezervasyonlar (dolu parklar): {park_based_reservations}")
        app.logger.info(f"🕰️ /assign_queued_time_slot - Mevcut Zaman Bazlı Kuyruk (çağrı başında, eleman sayısı: {len(zaman_bazli_bekleyen_talepler)}): {zaman_bazli_bekleyen_talepler[:3]}") # İlk 3'ünü logla, çok uzun olabilir

        if not zaman_bazli_bekleyen_talepler:
            app.logger.info("🕰️ /assign_queued_time_slot - Zaman bazlı kuyruk boş.")
            return jsonify({"status": "no_request_to_assign", "message": "Zaman bazlı talep kuyruğu boş."}), 200
        
        aktif_dolu_parklar = set()
        if isinstance(park_based_reservations, list):
            for park_res in park_based_reservations:
                if isinstance(park_res, dict) and park_res.get("parkid"):
                    aktif_dolu_parklar.add(park_res.get("parkid"))
        app.logger.info(f"🕰️ /assign_queued_time_slot - Aktif dolu parklar (CloudDB'den gelen): {aktif_dolu_parklar}")

        herhangi_bir_park_bos = False; bos_park_id = None
        for p_id in TUM_PARKLAR:
            if p_id not in aktif_dolu_parklar:
                herhangi_bir_park_bos = True; bos_park_id = p_id
                app.logger.info(f"🕰️ /assign_queued_time_slot - Boş fiziksel park bulundu: {bos_park_id}")
                break
        
        if herhangi_bir_park_bos and bos_park_id is not None: # bos_park_id'nin de dolu olduğundan emin ol
            atanacak_zaman_talebi = zaman_bazli_bekleyen_talepler.pop(0) # En yüksek öncelikli olanı al
            app.logger.info(f"🎉 /assign_queued_time_slot - Zaman bazlı talep atanıyor (ID: {atanacak_zaman_talebi.get('request_id')}, Park: {bos_park_id}): {atanacak_zaman_talebi}")
            app.logger.info(f"📊 /assign_queued_time_slot - Kalan Zaman Bazlı Kuyruk (eleman sayısı: {len(zaman_bazli_bekleyen_talepler)})")
            assigned_details = {
                "entryTime": atanacak_zaman_talebi.get("entryTime"), "exitTime": atanacak_zaman_talebi.get("exitTime"),
                "current": atanacak_zaman_talebi.get("current"), "desired": atanacak_zaman_talebi.get("desired"),
                "request_id": atanacak_zaman_talebi.get("request_id"), "assigned_timestamp": time.time(),
                "assigned_to_park_slot": bos_park_id # Atanan fiziksel park slotu
            }
            return jsonify({"status": "assigned", "assigned_details": assigned_details}), 200
        else:
            app.logger.info("🕰️ /assign_queued_time_slot - Zaman bazlı talep için uygun (boş) fiziksel park bulunamadı.")
            return jsonify({"status": "no_slot_found", "message": "Zaman bazlı talep için uygun fiziksel park bulunamadı."}), 200
    except Exception as e:
        app.logger.error(f"❌ /assign_queued_time_slot - Sunucu hatası: {str(e)}")
        app.logger.error(traceback.format_exc())
        return jsonify({"status": "error", "message": f"Zaman atama hatası: {str(e)}"}), 500

@app.route('/queued_time_based', methods=['GET'])
def queued_time_based_requests():
    try:
        app.logger.info(f"ℹ️ /queued_time_based çağrıldı. Mevcut Zaman Bazlı Kuyruk (eleman sayısı {len(zaman_bazli_bekleyen_talepler)}): {zaman_bazli_bekleyen_talepler[:5]}") # İlk 5'ini logla
        return jsonify({"status": "ok", "queued_time_based": zaman_bazli_bekleyen_talepler})
    except Exception as e:
        app.logger.error(f"❌ /queued_time_based - Sunucu hatası: {str(e)}")
        app.logger.error(traceback.format_exc())
        return jsonify({"status": "error", "message": f"Kuyruk bilgisi alınırken hata: {str(e)}"}), 500
# --- Flask Endpoint'leri SONU ---

# --- YENİ EKLENEN: YAPAY ZEKA İLE DİNAMİK FİYAT ENDPOINT'İ ---
@app.route('/get_ai_dynamic_price', methods=['GET'])
def get_ai_dynamic_price():
    app.logger.info(f"💡 /get_ai_dynamic_price endpoint'ine istek geldi.")
    if AI_MODEL is None:
        app.logger.error("❌ /get_ai_dynamic_price - Model yüklenemediği için fiyat hesaplanamıyor.")
        # Model yüklenememişse, belki sabit bir varsayılan fiyat veya hata mesajı dönebilirsiniz.
        # Ya da daha önce tanımladığınız BASE_PRICE_PARKING_AI'yi kullanabilirsiniz.
        return jsonify({
            "status": "error_model_unavailable",
            "message": "Dinamik fiyatlandırma modeli şu anda kullanılamıyor.",
            "dynamic_price_tl": BASE_PRICE_PARKING_AI # Varsayılan bir fiyat
        }), 503 # Service Unavailable

    try:
        current_time = datetime.now()
        hour = current_time.hour
        day_of_week = current_time.weekday()  # Pazartesi=0, Pazar=6
        month = current_time.month
        year = current_time.year # Modelimiz yılı da girdi olarak alıyordu

        # Modelin beklediği formatta bir DataFrame oluştur
        # Sütun adlarının eğitimdekiyle ('year', 'month', 'day_of_week', 'hour_of_day') aynı olması KRİTİK!
        input_features_df = pd.DataFrame([[year, month, day_of_week, hour]],
                                       columns=['year', 'month', 'day_of_week', 'hour_of_day'])

        app.logger.info(f"🧠 /get_ai_dynamic_price - Model için girdi özellikleri: {input_features_df.to_dict(orient='records')}")

        # Tahmin yap
        predicted_demand = AI_MODEL.predict(input_features_df)[0] # predict array döndürür, ilk elemanı alırız
        app.logger.info(f"📈 /get_ai_dynamic_price - Model tahmini (demand_unit): {predicted_demand:.2f}")

        # Tahmini fiyata dönüştür
        price = calculate_dynamic_price_from_ai(predicted_demand)
        app.logger.info(f"💲 /get_ai_dynamic_price - Hesaplanan dinamik fiyat: {price} TL")

        return jsonify({
            "status": "success",
            "current_timestamp": current_time.strftime('%Y-%m-%d %H:%M:%S'),
            "model_input_hour": hour,
            "model_input_day_of_week": day_of_week,
            "model_input_month": month,
            "model_input_year": year,
            "predicted_demand_unit": round(float(predicted_demand), 2), # JSON için float'a çevir
            "dynamic_price_tl": float(price) # JSON için float'a çevir
        })

    except Exception as e:
        app.logger.error(f"❌ /get_ai_dynamic_price - Fiyat hesaplama sırasında hata: {str(e)}")
        app.logger.error(traceback.format_exc()) # Detaylı hata logu terminale/dosyaya basılır
        return jsonify({"status": "error_calculation", "message": f"Dinamik fiyat hesaplanırken bir hata oluştu."}), 500
# --- YENİ EKLENEN ENDPOINT SONU ---


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5001)) # Portu 5000'den 5001'e değiştirdim, çakışma olmasın diye
    # debug=True üretimde False olmalı. Railway gibi ortamlarda zaten DEBUG ortam değişkeni ile yönetilebilir.
    app.run(host='0.0.0.0', port=port, debug=True)