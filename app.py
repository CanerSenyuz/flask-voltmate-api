from flask import Flask, request, jsonify
import time
import traceback # Hata ayıklama için eklendi
import math
import uuid # Benzersiz ID üretmek için
import os # Portu ortam değişkeninden almak için EKLENDİ

app = Flask(__name__)

# --- Global Değişkenler ---
# Park bazlı talepler için (eski sistemden)
bekleyen_talepler_park_bazli = [] # Orijinal `bekleyen_talepler` adını değiştirdim
recent_assignments_park_bazli = {} # Orijinal `recent_assignments` adını değiştirdim
RECENT_ASSIGNMENT_TIMEOUT = 5 # Park bazlı kilitler için
TUM_PARKLAR = ["A", "B", "C", "D"]

# Zaman bazlı talepler için YENİ kuyruk
zaman_bazli_bekleyen_talepler = []
# --- Global Değişkenler Sonu ---


# --- Yardımcı Fonksiyon (Eski Park Kilitlerini Temizlemek İçin) ---
def clean_recent_park_assignments(): # Fonksiyon adı güncellendi
    """Süresi dolmuş park atama kilitlerini temizler."""
    global recent_assignments_park_bazli # Değişken adı güncellendi
    now = time.time()
    keys_to_delete = [park for park, timestamp in recent_assignments_park_bazli.items() if now - timestamp > RECENT_ASSIGNMENT_TIMEOUT]
    if keys_to_delete:
        # print yerine app.logger.info kullanmak daha standarttır Flask'ta
        app.logger.info(f"🧹 Zaman aşımı: Şu park kilitleri kaldırılıyor: {keys_to_delete}")
        for key in keys_to_delete:
            if key in recent_assignments_park_bazli:
                del recent_assignments_park_bazli[key]

# --- Öncelik Hesaplama Fonksiyonu (Park Bazlı - Orijinal) ---
def calculate_priority_park(istek): # Fonksiyon adı güncellendi
    """Park bazlı talepler için öncelik puanı hesaplar."""
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

# --- Uyarlanmış `merge` ve `supersort` Fonksiyonları (Orijinal) ---
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
        elif key_func(M[i]) >= key_func(N[j]):
            merging_list.append(M[i])
            i += 1
        else:
            merging_list.append(N[j])
            j += 1
    return merging_list

def supersort_requests(requests_list, key_func):
    n = len(requests_list)
    if n <= 1:
        return requests_list[:]
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


# --- Flask Endpoint'leri ---

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
                
                request_timestamp_id = time.time() + hash(str(yeni_istek)) + hash(yeni_istek.get("parkid",""))
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
        if not doluluk and requests_input:
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
                if park_id and doluluk.get(park_id, 1) == 0:
                    uygun_talepler_onerisi.append(istek)
            
            if requests_input and requests_input[0].get("parkid") and doluluk.get(requests_input[0].get("parkid"), 1) == 0:
                if not any(r.get("parkid") == requests_input[0].get("parkid") for r in uygun_talepler_onerisi):
                     uygun_talepler_onerisi.append(requests_input[0])

            if not uygun_talepler_onerisi and not is_full:
                for park_id_key in TUM_PARKLAR:
                    if doluluk.get(park_id_key, 1) == 0:
                         uygun_talepler_onerisi.append({"parkid": park_id_key, "current":0, "desired":0, "message":"Bu park boş"})

            sirali_uygun_oneriler = supersort_requests(uygun_talepler_onerisi, calculate_priority_park)
            app.logger.info(f"📊 /predict (park-bazlı) - Parklar boş/kısmen boş, öneri listesi: {sirali_uygun_oneriler}")
            return jsonify({"status": "success", "sirali_istekler": sirali_uygun_oneriler})

    except Exception as e:
        app.logger.error(f"❌ /predict (park-bazlı) - Sunucu hatası: {str(e)}")
        traceback.print_exc()
        return jsonify({"status": "error", "message": f"Sunucu hatası: {str(e)}"}), 500

@app.route('/assign', methods=['POST'])
def assign_park_based_request():
    global bekleyen_talepler_park_bazli, recent_assignments_park_bazli
    clean_recent_park_assignments()
    try:
        data = request.get_json()
        if not data:
            return jsonify({"status": "error", "message": "İstek gövdesi boş veya JSON değil."}), 400
        doluluk = data.get("doluluk", {})

        app.logger.info(f"🅿️ /assign (park-bazlı) çağrıldı. Gelen doluluk: {doluluk}")
        app.logger.info(f"🅿️ /assign (park-bazlı) - Mevcut Park Kuyruğu: {bekleyen_talepler_park_bazli}")
        app.logger.info(f"🅿️ /assign (park-bazlı) - Aktif Park Kilitleri: {recent_assignments_park_bazli}")

        if not bekleyen_talepler_park_bazli:
            app.logger.info("🅿️ /assign (park-bazlı) - Park kuyruğu boş.")
            return jsonify({"status": "empty", "message": "Park kuyruğu boş."}), 200

        atanacak_talep = None
        index_to_pop = -1
        atanan_park_id = None # Tanımlama eklendi

        for i, talep in enumerate(bekleyen_talepler_park_bazli):
            istenen_park = talep.get("parkid")
            if istenen_park and doluluk.get(istenen_park, 1) == 0 and istenen_park not in recent_assignments_park_bazli:
                atanacak_talep = talep
                index_to_pop = i
                atanan_park_id = istenen_park
                break
        
        if not atanacak_talep:
            for park_id_bos_aday in TUM_PARKLAR: # Değişken adı çakışmaması için güncellendi
                if doluluk.get(park_id_bos_aday, 1) == 0 and park_id_bos_aday not in recent_assignments_park_bazli:
                    if bekleyen_talepler_park_bazli:
                        atanacak_talep = bekleyen_talepler_park_bazli[0]
                        index_to_pop = 0
                        atanan_park_id = park_id_bos_aday
                        break
        
        if atanacak_talep and index_to_pop != -1 and atanan_park_id is not None: # atanan_park_id kontrolü eklendi
            secilen_talep = bekleyen_talepler_park_bazli.pop(index_to_pop)
            app.logger.info(f"🅿️ /assign (park-bazlı) - Atama: Talep {secilen_talep.get('request_id')} -> Park {atanan_park_id}")
            app.logger.info(f"🅿️ /assign (park-bazlı) - Kalan park kuyruğu: {bekleyen_talepler_park_bazli}")
            recent_assignments_park_bazli[atanan_park_id] = time.time()
            app.logger.info(f"🅿️ /assign (park-bazlı) - Park {atanan_park_id} kilitlendi.")
            
            atanan_bilgisi = {
                "parkid": atanan_park_id,
                "current": secilen_talep.get("current"),
                "desired": secilen_talep.get("desired"),
                "arrival_time": secilen_talep.get("arrival_time"),
                "departure_time": secilen_talep.get("departure_time"),
                "original_parkid": secilen_talep.get("parkid"),
                "request_id": secilen_talep.get("request_id"),
                "assigned_timestamp": time.time()
            }
            app.logger.info(f"🅿️ /assign (park-bazlı) - Android'e dönülecek: {atanan_bilgisi}")
            return jsonify({"status": "assigned", "assigned": atanan_bilgisi})
        else:
            app.logger.info("🅿️ /assign (park-bazlı) - Uygun park bulunamadı veya kuyrukta uygun talep yok.")
            if all(doluluk.get(p, 1) == 1 for p in TUM_PARKLAR if p in doluluk):
                 return jsonify({"status": "full", "message": "Tüm parklar dolu."}), 200
            else:
                 return jsonify({"status": "no_spot_available", "message": "Uygun (boş ve kilitsiz) park bulunamadı."}), 200

    except Exception as e:
        app.logger.error(f"❌ /assign (park-bazlı) Hatası: {e}")
        traceback.print_exc()
        return jsonify({"status": "error", "message": f"Park atama hatası: {str(e)}"}), 500

# --- YENİ ZAMAN BAZLI ENDPOINT'LER ---

@app.route('/predict_time_slot', methods=['POST'])
def predict_time_slot():
    global zaman_bazli_bekleyen_talepler
    try:
        data = request.get_json()
        if not data:
            return jsonify({"status": "error", "message": "İstek gövdesi boş veya JSON değil."}), 400

        new_time_request = data.get("new_time_request")
        # park_based_reservations = data.get("park_based_reservations", []) # Bu bilgi şimdilik loglanıyor, iş mantığında kullanılmıyor

        app.logger.info(f"🕰️ /predict_time_slot - Gelen yeni zaman talebi: {new_time_request}")
        # app.logger.info(f"🕰️ /predict_time_slot - Gelen park bazlı rezervasyonlar (bilgi amaçlı): {park_based_reservations}")

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
            "status": "queued",
            "request_id": new_time_request['request_id'],
            "message": "Zaman bazlı şarj talebiniz kuyruğa alındı."
        }), 200

    except Exception as e:
        app.logger.error(f"❌ /predict_time_slot - Sunucu hatası: {str(e)}")
        traceback.print_exc()
        return jsonify({"status": "error", "message": f"Zaman talebi işleme hatası: {str(e)}"}), 500

@app.route('/assign_queued_time_slot', methods=['POST'])
def assign_queued_time_slot():
    global zaman_bazli_bekleyen_talepler
    try:
        data = request.get_json()
        if not data:
            return jsonify({"status": "error", "message": "İstek gövdesi boş veya JSON değil."}), 400
        
        park_based_reservations = data.get("park_based_reservations", [])
        app.logger.info(f"🕰️ /assign_queued_time_slot - Çağrıldı.")
        app.logger.info(f"🕰️ /assign_queued_time_slot - Gelen park bazlı rezervasyonlar: {park_based_reservations}")
        app.logger.info(f"🕰️ /assign_queued_time_slot - Mevcut Zaman Bazlı Kuyruk (çağrı başında, eleman sayısı: {len(zaman_bazli_bekleyen_talepler)}): {zaman_bazli_bekleyen_talepler}")

        if not zaman_bazli_bekleyen_talepler:
            app.logger.info("🕰️ /assign_queued_time_slot - Zaman bazlı kuyruk boş.")
            return jsonify({"status": "no_request_to_assign", "message": "Zaman bazlı talep kuyruğu boş."}), 200

        aktif_dolu_parklar = set()
        if isinstance(park_based_reservations, list):
            for park_res in park_based_reservations:
                if isinstance(park_res, dict) and park_res.get("parkid"):
                    aktif_dolu_parklar.add(park_res.get("parkid"))
        
        app.logger.info(f"🕰️ /assign_queued_time_slot - Aktif dolu parklar (CloudDB'den gelen): {aktif_dolu_parklar}")

        herhangi_bir_park_bos = False
        bos_park_id = None # Atama için boş park ID'sini sakla
        for p_id in TUM_PARKLAR:
            if p_id not in aktif_dolu_parklar:
                herhangi_bir_park_bos = True
                bos_park_id = p_id # İlk boş parkı al
                app.logger.info(f"🕰️ /assign_queued_time_slot - Boş fiziksel park bulundu: {bos_park_id}")
                break
        
        if herhangi_bir_park_bos:
            atanacak_zaman_talebi = zaman_bazli_bekleyen_talepler.pop(0) # Kuyruktan ilkini al
            app.logger.info(f"🎉 /assign_queued_time_slot - Zaman bazlı talep atanıyor (ID: {atanacak_zaman_talebi.get('request_id')}): {atanacak_zaman_talebi}")
            app.logger.info(f"📊 /assign_queued_time_slot - Kalan Zaman Bazlı Kuyruk (eleman sayısı: {len(zaman_bazli_bekleyen_talepler)}): {zaman_bazli_bekleyen_talepler}")

            assigned_details = {
                "entryTime": atanacak_zaman_talebi.get("entryTime"),
                "exitTime": atanacak_zaman_talebi.get("exitTime"),
                "current": atanacak_zaman_talebi.get("current"),
                "desired": atanacak_zaman_talebi.get("desired"),
                "request_id": atanacak_zaman_talebi.get("request_id"),
                "assigned_timestamp": time.time(),
                "assigned_to_park_slot": bos_park_id # Hangi fiziksel slotun uygun olduğuna dair bilgi (opsiyonel)
            }
            return jsonify({"status": "assigned", "assigned_details": assigned_details}), 200
        else:
            app.logger.info("🕰️ /assign_queued_time_slot - Zaman bazlı talep için uygun (boş) fiziksel park bulunamadı.")
            return jsonify({"status": "no_slot_found", "message": "Zaman bazlı talep için uygun fiziksel park bulunamadı."}), 200

    except Exception as e:
        app.logger.error(f"❌ /assign_queued_time_slot - Sunucu hatası: {str(e)}")
        traceback.print_exc()
        return jsonify({"status": "error", "message": f"Zaman atama hatası: {str(e)}"}), 500

@app.route('/queued_time_based', methods=['GET'])
def queued_time_based_requests():
    try:
        app.logger.info(f"ℹ️ /queued_time_based çağrıldı. Mevcut Zaman Bazlı Kuyruk (eleman sayısı {len(zaman_bazli_bekleyen_talepler)}): {zaman_bazli_bekleyen_talepler}")
        return jsonify({"status": "ok", "queued_time_based": zaman_bazli_bekleyen_talepler})
    except Exception as e:
        app.logger.error(f"❌ /queued_time_based - Sunucu hatası: {str(e)}")
        traceback.print_exc()
        return jsonify({"status": "error", "message": f"Kuyruk bilgisi alınırken hata: {str(e)}"}), 500


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=True)
