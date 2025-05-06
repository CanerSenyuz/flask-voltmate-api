# app.py (Supersort Kullanımı)

from flask import Flask, request, jsonify
import time
import traceback # Hata ayıklama için eklendi
import math

app = Flask(__name__)

# --- Global Değişkenler ---
bekleyen_talepler = []
recent_assignments = {}
RECENT_ASSIGNMENT_TIMEOUT = 5
TUM_PARKLAR = ["A", "B", "C", "D"]
# --- Global Değişkenler Sonu ---


# --- Yardımcı Fonksiyon (Eski Kilitleri Temizlemek İçin) ---
def clean_recent_assignments():
    """Süresi dolmuş atama kilitlerini temizler."""
    global recent_assignments
    now = time.time()
    keys_to_delete = [park for park, timestamp in recent_assignments.items() if now - timestamp > RECENT_ASSIGNMENT_TIMEOUT]
    if keys_to_delete:
        print(f"🧹 Zaman aşımı: Şu park kilitleri kaldırılıyor: {keys_to_delete}")
        for key in keys_to_delete:
             if key in recent_assignments:
                 del recent_assignments[key]

# --- Öncelik Hesaplama Fonksiyonu ---
def calculate_priority(istek):
    """Talepler için öncelik puanı hesaplar (Yüksek puan = Yüksek öncelik)."""
    current = istek.get("current", 0)
    desired = istek.get("desired", 100)
    arrival_time = istek.get("arrival_time")
    departure_time = istek.get("departure_time")
    charge_need_priority = max(0, desired - current)
    urgency_priority = 0
    now = time.time()
    if departure_time and departure_time > now:
        time_to_departure = departure_time - now
        urgency_priority = max(0, 5000 - time_to_departure) / 50
    wait_priority = 0
    if arrival_time and arrival_time < now:
        wait_priority = (now - arrival_time) / 300
    total_priority = (charge_need_priority * 1.5) + (urgency_priority * 1.0) + (wait_priority * 0.5)
    return total_priority

# --- Uyarlanmış `merge` Fonksiyonu (AZALAN sıralama için) ---
def merge_requests(M, N, key_func):
    """İki TALEP listesini key_func'a göre AZALAN sırada birleştirir."""
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
        # Yüksek öncelikli (büyük değer) önce gelir
        elif key_func(M[i]) >= key_func(N[j]):
            merging_list.append(M[i])
            i += 1
        else:
            merging_list.append(N[j])
            j += 1
    return merging_list

# --- Uyarlanmış `supersort` Fonksiyonu ---
# Not: Bu algoritma standart merge sort'tan farklı çalışır.
# Standart `sorted()` genellikle daha basit ve verimlidir.
def supersort_requests(requests_list, key_func):
    """Verilen talep listesini key_func'a göre AZALAN sırada sıralar."""
    n = len(requests_list)
    if n <= 1:
        return requests_list[:] # Kopyasını döndür

    # İleri ve Geri Seçim (Orijinal algoritmayı korumak adına)
    # Bu seçimler artan sıraya göre yapılıyor gibi görünüyor,
    # ancak merge_requests azalan yaptığı için sonuca etki etmeli.
    forward_selected = []
    backward_selected = []
    remaining_indices = list(range(n))

    # İLERİ SEÇİM (Monoton Artan Öncelik - Düşükten Yükseğe)
    forward_indices_to_remove = []
    current_idx_in_fwd = -1
    for idx in remaining_indices:
        priority = key_func(requests_list[idx])
        if current_idx_in_fwd == -1 or priority >= key_func(requests_list[current_idx_in_fwd]):
             forward_selected.append(requests_list[idx])
             forward_indices_to_remove.append(idx)
             current_idx_in_fwd = idx
    remaining_indices = [idx for idx in remaining_indices if idx not in forward_indices_to_remove]

    # GERİ SEÇİM (Monoton Artan Öncelik - Tersten)
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

    # --- Özyineleme (Kalan Liste Üzerinde) ---
    mid = len(remaining_requests) // 2
    left_sublist = remaining_requests[:mid]
    right_sublist = remaining_requests[mid:]
    sorted_left = supersort_requests(left_sublist, key_func)
    sorted_right = supersort_requests(right_sublist, key_func)

    # --- Birleştirme ---
    merged_recursive = merge_requests(sorted_left, sorted_right, key_func)
    merged_selection = merge_requests(forward_selected, backward_selected, key_func)
    final_sorted_list = merge_requests(merged_selection, merged_recursive, key_func)

    return final_sorted_list


# --- Flask Endpoint'leri ---

@app.route('/predict', methods=['POST'])
def predict():
    global bekleyen_talepler
    try:
        data = request.get_json()
        doluluk = data.get("doluluk", {})
        requests_input = data.get("requests", [])

        print(f"📥 /predict - Gelen doluluk: {doluluk}")
        print(f"📥 /predict - Gelen requests_input (Yeni): {requests_input}")

        if not isinstance(requests_input, list):
            return jsonify({"status": "error", "message": "'requests' bir liste olmalı."}), 400

        last_saved_request = None
        yeni_eklenen_sayisi = 0

        if requests_input:
            for yeni_istek in requests_input:
                if 'arrival_time' not in yeni_istek: yeni_istek['arrival_time'] = time.time()
                if 'departure_time' not in yeni_istek: yeni_istek['departure_time'] = time.time() + 7200
                request_timestamp_id = time.time() + hash(str(yeni_istek))
                yeni_istek['timestamp'] = request_timestamp_id
                yeni_istek['request_id'] = request_timestamp_id

                if not any(r.get('request_id') == yeni_istek['request_id'] for r in bekleyen_talepler):
                    bekleyen_talepler.append(yeni_istek)
                    last_saved_request = yeni_istek
                    yeni_eklenen_sayisi += 1
                    print(f"➕ /predict - Kuyruğa eklendi (ID'li): {yeni_istek}")
                else:
                    print(f"⚠️ /predict - Tekrarlanan istek atlandı (ID: {yeni_istek.get('request_id')})")

        if yeni_eklenen_sayisi > 0:
            print(f"📊 /predict - Yeni talep(ler) eklendi, kuyruk yeniden sıralanıyor...")
            print(f"📊 Önceki Sırasız Kuyruk: {bekleyen_talepler}")
            # *** Supersort Kullanımı ***
            bekleyen_talepler = supersort_requests(bekleyen_talepler, calculate_priority)
            # *** Sıralama Sonu ***
            print(f"📊 /predict - Kuyruk sıralandı (Supersort ile). Güncel Sıralı Kuyruk: {bekleyen_talepler}")

        # Yanıtı belirle (Parkların dolu/boş durumuna göre)
        is_full = all(doluluk.get(p, 1) == 1 for p in TUM_PARKLAR)
        if is_full:
             if last_saved_request:
                 return jsonify({"status": "full", "message": "Tüm park alanları dolu...", "saved_request": last_saved_request}), 200
             else:
                  return jsonify({"status": "full", "message": "Tüm park alanları dolu."}), 200
        else:
             # Parklar boşsa öneri döndür (ChargingActivity için)
             extra_requests = data.get("extra_requests", []) # Bu durumda extra_requests lazım olabilir
             mevcut_park_talepleri = set(r.get("parkid") for r in extra_requests)
             uygun_talepler = []
             for istek in extra_requests:
                 park_id = istek.get("parkid")
                 if park_id and doluluk.get(park_id, 1) == 0:
                     uygun_talepler.append(istek)
             # Uygun talepleri de supersort ile sıralayabiliriz
             sirali_uygun = supersort_requests(uygun_talepler, calculate_priority)
             print(f"📊 /predict - Parklar boş, öneri listesi (Supersort ile): {sirali_uygun}")
             return jsonify({"status": "success", "sirali_istekler": sirali_uygun})

    except Exception as e:
        print(f"❌ /predict - Sunucu hatası: {str(e)}")
        traceback.print_exc()
        return jsonify({"status": "error", "message": f"Sunucu hatası: {str(e)}"}), 500


@app.route('/queued', methods=['GET'])
def queued_requests():
    # Kuyruk her zaman sıralı tutulduğu için direkt döndür
    print(f"ℹ️ /queued çağrıldı. Mevcut Sıralı Kuyruk: {bekleyen_talepler}")
    return jsonify({"status": "ok", "queued": bekleyen_talepler})


@app.route('/assign', methods=['POST'])
def assign_request():
    # ... (Bu endpoint aynı kalır, kuyruk zaten sıralı) ...
    global bekleyen_talepler, recent_assignments
    clean_recent_assignments()
    try:
        data = request.get_json()
        doluluk = data.get("doluluk", {})
        print(f"🅿️ /assign çağrıldı. Gelen doluluk: {doluluk}")
        print(f"🅿️ Mevcut Sıralı Kuyruk: {bekleyen_talepler}")
        print(f"🅿️ Aktif Kilitler: {recent_assignments}")

        if not bekleyen_talepler:
             print("🅿️ Kuyruk boş.")
             return jsonify({"status": "empty", "message": "Kuyruk boş."}), 200

        atanacak_talep = bekleyen_talepler[0]
        print(f"🅿️ Aday talep: {atanacak_talep}")

        atanan_park = None
        possible_parks = [p for p, status in doluluk.items() if status == 0 and p in TUM_PARKLAR]
        print(f"🅿️ Boş park adayları: {possible_parks}")

        for park_id in possible_parks:
            if park_id in recent_assignments:
                print(f"🅿️ Park {park_id} kilitli, atlandı.")
                continue
            atanan_park = park_id
            print(f"🅿️ Boş ve kilitsiz park bulundu: {atanan_park}")
            break

        if atanan_park is not None:
            secilen_talep = bekleyen_talepler.pop(0)
            print(f"🅿️ Atama: Talep {secilen_talep.get('request_id')} -> Park {atanan_park}")
            print(f"🅿️ Kalan kuyruk: {bekleyen_talepler}")
            recent_assignments[atanan_park] = time.time()
            print(f"🅿️ Park {atanan_park} kilitlendi.")
            atanan_bilgisi = { # ... (yanıt objesi) ...
                 "parkid": atanan_park, "current": secilen_talep.get("current"),
                 "desired": secilen_talep.get("desired"), "arrival_time": secilen_talep.get("arrival_time"),
                 "departure_time": secilen_talep.get("departure_time"), "original_parkid": secilen_talep.get("parkid"),
                 "request_id": secilen_talep.get("request_id"), "assigned_timestamp": time.time()
            }
            print(f"🅿️ Android'e dönülecek: {atanan_bilgisi}")
            return jsonify({"status": "assigned", "assigned": atanan_bilgisi})
        else:
            print("🅿️ Uygun park bulunamadı.")
            return jsonify({"status": "no_spot_available", "message": "Uygun park bulunamadı."}), 200

    except Exception as e:
        print(f"❌ /assign Hatası: {e}")
        traceback.print_exc()
        return jsonify({"status": "error", "message": f"Atama hatası: {str(e)}"}), 500


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
