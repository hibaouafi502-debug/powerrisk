# =========================================================
# IMPORTS (Nettoyés - sans répétitions)
# =========================================================
import streamlit as st
import pandas as pd
import numpy as np
import pdfplumber
import re
import requests
import matplotlib.pyplot as plt
import mysql.connector
import bcrypt
import random
import smtplib
import tempfile
import os
import pytesseract
from statsmodels.tsa.arima.model import ARIMA
from sklearn.ensemble import RandomForestRegressor
from sklearn.naive_bayes import GaussianNB
from sklearn.linear_model import LogisticRegression
from PIL import Image
from streamlit_js_eval import streamlit_js_eval
from email.mime.text import MIMEText
from datetime import datetime, timedelta
from scipy.stats import norm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.pagesizes import A4
import plotly.express as px
import plotly.graph_objects as go
import google.generativeai as genai

# =========================================================
# DATABASE
# =========================================================
conn = mysql.connector.connect(
    host="localhost",
    user="root",
    password="Hiba1221+",
    database="powerrisk"
)
cursor = conn.cursor()

# =========================================================
# EMAIL (avec message de bienvenue)
# =========================================================
def send_email(receiver_email, subject, body, is_welcome=False, user_name=""):
    sender_email = "powerrisk22@gmail.com"
    sender_password = "sfygmvinfkqiarkk"

    if is_welcome:
        welcome_msg = f"""
        Bonjour {user_name},

        Bienvenue sur PowerRisk, la plateforme intelligente de gestion des risques électriques.

        Avec PowerRisk, vous pourrez :
        - Analyser vos consommations électriques
        - Prévoir les coupures grâce à l'IA
        - Recevoir des solutions personnalisées (énergie solaire, batteries, maintenance)
        - Gagner des points à chaque action

        Votre code de vérification est : {body}

        Cordialement,
        L'équipe PowerRisk
        """
        body = welcome_msg

    try:
        msg = MIMEText(body, "plain", "utf-8")
        msg["Subject"] = subject
        msg["From"] = sender_email
        msg["To"] = receiver_email
        server = smtplib.SMTP("smtp.gmail.com", 587)
        server.starttls()
        server.login(sender_email, sender_password)
        server.sendmail(sender_email, receiver_email, msg.as_string())
        server.quit()
        return True
    except Exception as e:
        print("Email error:", e)
        return False

# =========================================================
# AUTHENTIFICATION (corrigée)
# =========================================================
def register_user(data):
    cursor.execute("SELECT id FROM users WHERE email=%s", (data["email"],))
    if cursor.fetchone():
        return "EMAIL_EXISTS"

    hashed = bcrypt.hashpw(data["password"].encode(), bcrypt.gensalt()).decode()
    code = str(random.randint(100000, 999999))

    cursor.execute("""
        INSERT INTO users (nom_complet, email, mot_de_passe, verification_code, is_verified)
        VALUES (%s, %s, %s, %s, FALSE)
    """, (data["nom"], data["email"], hashed, code))
    conn.commit()
    user_id = cursor.lastrowid

    cursor.execute("""
        INSERT INTO entreprises
        (user_id, nom_entreprise, secteur_activite, taille_entreprise, wilaya,
         email_professionnel, type_installation, puissance_installee_kva,
         consommation_moyenne_kwh, nombre_coupures_mois,
         numero_telephone, temperature_moyenne_regionale,
         objectif_utilisation, energie_alternative, etat_equipements,
         frequence_maintenance, dernier_incident, type_contrat_assurance)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s, %s, %s, %s)
    """, (
        user_id, data["nom_entreprise"], data["secteur"], data["taille"], data["wilaya"],
        data["email"], data["type_installation"], data["puissance"],
        data["consommation"], data["coupures"], data["telephone"],
        data["temperature"], data["objectif"], data["energie_alt"],
        data["etat"], data["maintenance"], data["incident"], data["contrat"]
    ))
    conn.commit()
    cursor.execute("INSERT INTO points (user_id, total_points, used_points) VALUES (%s, 20, 0)", (user_id,))
    conn.commit()

    send_email(data["email"], "Bienvenue sur PowerRisk", code, is_welcome=True, user_name=data["nom"])
    return "SUCCESS"

def verify_account(email, code):
    cursor.execute("SELECT id FROM users WHERE email=%s AND verification_code=%s", (email, code))
    user = cursor.fetchone()
    if not user:
        return None
    cursor.execute("UPDATE users SET is_verified=TRUE, verification_code=NULL WHERE id=%s", (user[0],))
    conn.commit()
    return user[0]

def login_user(email, password):
    cursor.execute("SELECT id, mot_de_passe, is_verified FROM users WHERE email=%s", (email,))
    user = cursor.fetchone()
    if not user:
        return None
    user_id, hashed, verified = user
    if not verified:
        return "NOT_VERIFIED"
    if not bcrypt.checkpw(password.encode(), hashed.encode()):
        return None
    return user_id

def forgot_password(email):
    cursor.execute("SELECT id FROM users WHERE email=%s", (email,))
    user = cursor.fetchone()
    if not user:
        return False
    code = str(random.randint(100000, 999999))
    cursor.execute("UPDATE users SET reset_code=%s WHERE id=%s", (code, user[0]))
    conn.commit()
    body = f"Votre code de réinitialisation PowerRisk est : {code}\n\nSi vous n'avez pas demandé cette réinitialisation, ignorez cet email."
    send_email(email, "Réinitialisation mot de passe PowerRisk", body, is_welcome=False)
    return True

def reset_password(email, code, new_password):
    cursor.execute("SELECT id FROM users WHERE email=%s AND reset_code=%s", (email, code))
    user = cursor.fetchone()
    if not user:
        return False
    hashed = bcrypt.hashpw(new_password.encode(), bcrypt.gensalt()).decode()
    cursor.execute("UPDATE users SET mot_de_passe=%s, reset_code=NULL WHERE id=%s", (hashed, user[0]))
    conn.commit()
    return True

def get_points(user_id):
    cursor.execute("SELECT total_points, used_points FROM points WHERE user_id=%s", (user_id,))
    data = cursor.fetchone()
    return data[0] - data[1] if data else 0

def use_points(user_id, amount):
    if get_points(user_id) < amount:
        return False
    cursor.execute("UPDATE points SET used_points = used_points + %s WHERE user_id=%s", (amount, user_id))
    conn.commit()
    return True

# =========================================================
# EXTRACTION PDF (corrigée)
# =========================================================
def extract_electricity_from_pdf(pdf_file):
    if pdf_file is None:
        return None
    text = ""
    try:
        with pdfplumber.open(pdf_file) as pdf:
            for page in pdf.pages:
                page_text = page.extract_text()
                if page_text:
                    text += page_text
        match = re.search(r"(\d+[.,]?\d*)\s*kWh", text, re.IGNORECASE)
        if match:
            return float(match.group(1).replace(",", "."))
        else:
            return None
    except:
        return None

# =========================================================
# WEATHER (optionnel)
# =========================================================
@st.cache_data
def get_weather_forecast(lat, lon):
    try:
        api_key = "fd6a9aa64777078b3f7c711fb754b431"
        url = f"http://api.openweathermap.org/data/2.5/forecast?lat={lat}&lon={lon}&appid={api_key}&units=metric"
        response = requests.get(url, timeout=10)
        if response.status_code == 200:
            data = response.json()
            temp = data["list"][0]["main"]["temp"]
            wind = data["list"][0]["wind"]["speed"]
            place = f'{data["city"]["name"]}, {data["city"]["country"]}'
            forecast = [{"date": item["dt_txt"], "temp": item["main"]["temp"], "wind": item["wind"]["speed"]} for item in data["list"]]
            return temp, wind, place, forecast
    except:
        pass
    return None, None, "Erreur", []

# =========================================================
# INTERFACE PRINCIPALE
# =========================================================
st.set_page_config(page_title="PowerRisk", layout="wide")
st.title("🔐 PowerRisk - Gestion Intelligente des Risques Électriques")

# Initialisation session_state
if "user_id" not in st.session_state:
    st.session_state.user_id = None
if "verify_email" not in st.session_state:
    st.session_state.verify_email = None
if "consommations" not in st.session_state:
    st.session_state.consommations = []
if "lambda_panne" not in st.session_state:
    st.session_state.lambda_panne = 0.1
if "temperature" not in st.session_state:
    st.session_state.temperature = 25.0
if "wind" not in st.session_state:
    st.session_state.wind = 10.0
if "voltage" not in st.session_state:
    st.session_state.voltage = 220
if "current" not in st.session_state:
    st.session_state.current = 30

# ================= AUTHENTIFICATION =================
if st.session_state.user_id is None:
    menu = st.radio("Choisissez :", ["Se connecter", "Créer un compte"])

    if menu == "Se connecter":
        email = st.text_input("Email")
        password = st.text_input("Mot de passe", type="password")
        if st.button("Se connecter"):
            result = login_user(email, password)
            if result == "NOT_VERIFIED":
                st.warning("Veuillez vérifier votre email.")
            elif result:
                st.session_state.user_id = result
                st.success("Connexion réussie")
                st.rerun()
            else:
                st.error("Email ou mot de passe incorrect.")

        st.markdown("---")
        st.subheader("Mot de passe oublié")
        fp_email = st.text_input("Email pour réinitialisation")
        if st.button("Envoyer code"):
            if forgot_password(fp_email):
                st.success("Code envoyé par email.")
            else:
                st.error("Email introuvable.")
        reset_code = st.text_input("Code reçu")
        new_password = st.text_input("Nouveau mot de passe", type="password")
        if st.button("Réinitialiser"):
            if reset_password(fp_email, reset_code, new_password):
                st.success("Mot de passe mis à jour.")
            else:
                st.error("Code incorrect.")

    elif menu == "Créer un compte":
        st.subheader("Informations obligatoires")
        nom = st.text_input("Nom complet")
        nom_entreprise = st.text_input("Nom entreprise")
        secteur = st.selectbox("Secteur", ["Industrie","Énergie","BTP","Hôpital"])
        taille = st.selectbox("Taille", ["Petite","Moyenne","Grande"])
        wilaya = st.text_input("Wilaya")
        email = st.text_input("Email professionnel")
        type_installation = st.selectbox("Type installation", ["BT","MT","HT"])
        puissance = st.number_input("Puissance kVA", min_value=0)
        consommation = st.number_input("Consommation kWh", min_value=0)
        coupures = st.number_input("Coupures/mois", min_value=0)
        password = st.text_input("Mot de passe", type="password")

        st.subheader("Informations optionnelles")
        telephone = st.text_input("Téléphone")
        temperature = st.number_input("Température", value=0.0)
        objectif = st.selectbox("Objectif", ["Surveillance interne", "Audit énergétique", "Prévention des pannes", "Assurance"])
        energie_alt = st.selectbox("Énergie alternative", ["Générateur","Panneaux solaires","UPS"])
        etat = st.selectbox("État équipements", ["Ancienne","Moderne"])
        maintenance = st.text_input("Fréquence maintenance")
        incident = st.date_input("Dernier incident")
        contrat = st.text_input("Contrat assurance")

        if st.button("Créer mon compte"):
            data = {
                "nom": nom, "email": email, "password": password,
                "nom_entreprise": nom_entreprise, "secteur": secteur, "taille": taille,
                "wilaya": wilaya, "type_installation": type_installation, "puissance": puissance,
                "consommation": consommation, "coupures": coupures, "telephone": telephone,
                "temperature": temperature, "objectif": objectif, "energie_alt": energie_alt,
                "etat": etat, "maintenance": maintenance, "incident": incident, "contrat": contrat
            }
            result = register_user(data)
            if result == "EMAIL_EXISTS":
                st.error("Email existe déjà.")
            else:
                st.session_state.verify_email = email
                st.success("Code envoyé. Vérifiez votre email.")

    # Vérification
    if st.session_state.verify_email:
        st.subheader("Vérification du compte")
        code = st.text_input("Entrez le code reçu")
        if st.button("Vérifier mon compte"):
            user_id = verify_account(st.session_state.verify_email, code)
            if user_id:
                st.session_state.user_id = user_id
                st.session_state.verify_email = None
                st.success("Compte activé 🎉")
                st.rerun()
            else:
                st.error("Code incorrect.")

# ================= APRÈS CONNEXION =================
if st.session_state.user_id:
    # Sidebar avec bouton déconnexion
    st.sidebar.image("Logo.jpg",width=120)
    st.sidebar.markdown("## ⚡ Power Risk")
    st.sidebar.markdown("Plateforme d'analyse avancée")
    menu = st.sidebar.radio(
        "Navigation",
        ["Dashboard Intelligent", "Données", "Analyse", "Rapport", "Prévision", "Solutions"]
    )
    if st.sidebar.button("Se déconnecter"):
        st.session_state.user_id = None
        st.rerun()

    points = get_points(st.session_state.user_id)
    st.sidebar.info(f"💰 Points disponibles: {points}")

    # Style Glass
    st.markdown("""
    <style>
    body { background: linear-gradient(135deg, #0f2027, #203a43, #2c5364); }
    .glass { background: rgba(255,255,255,0.1); backdrop-filter: blur(15px); padding: 25px; border-radius: 20px; color: white; }
    .kpi-value { font-size: 35px; font-weight: bold; }
    </style>
    """, unsafe_allow_html=True)

    # ========== PAGE DASHBOARD INTELLIGENT ==========
if menu == "Dashboard Intelligent":
        st.markdown("<h1 style='color:white;'>📊 Tableau de Bord Stratégique</h1>", unsafe_allow_html=True)
        dates = pd.date_range(start="2024-01-01", periods=60)
        risques = np.random.randint(20, 100, 60)
        incidents = np.random.randint(1, 15, 60)
        df_dash = pd.DataFrame({"Date": dates, "Niveau de Risque": risques, "Incidents": incidents})

        col1, col2, col3 = st.columns(3)
        col1.markdown(f"<div class='glass'><div>Risque Moyen</div><div class='kpi-value'>{df_dash['Niveau de Risque'].mean():.1f}%</div></div>", unsafe_allow_html=True)
        col2.markdown(f"<div class='glass'><div>Total Incidents</div><div class='kpi-value'>{df_dash['Incidents'].sum()}</div></div>", unsafe_allow_html=True)
        col3.markdown(f"<div class='glass'><div>Pic de Risque</div><div class='kpi-value'>{df_dash['Niveau de Risque'].max()}%</div></div>", unsafe_allow_html=True)

        fig1 = px.line(df_dash, x="Date", y="Niveau de Risque", title="Évolution Dynamique du Risque", markers=True)
        fig1.update_layout(template="plotly_dark")
        st.plotly_chart(fig1, use_container_width=True)

        fig2 = px.bar(df_dash, x="Date", y="Incidents", title="Distribution des Incidents")
        fig2.update_layout(template="plotly_dark")
        st.plotly_chart(fig2, use_container_width=True)

        fig3 = go.Figure(go.Indicator(mode="gauge+number", value=df_dash["Niveau de Risque"].mean(), title={'text': "Indice Global de Risque"}, gauge={'axis': {'range': [0,100]}, 'bar': {'color': "red"}}))
        fig3.update_layout(template="plotly_dark")
        st.plotly_chart(fig3, use_container_width=True)

    # ========== PAGE DONNÉES (corrigée) ==========
elif menu == "Données":
    st.title("📁 Gestion des Données Industrielles")
    
    # =====================================================
    # 📍 GPS + Météo (Ajouté)
    # =====================================================
    st.subheader("🌤️ Conditions météo actuelles")
    
    # محاولة جلب الموقع تلقائياً
    if "lat" not in st.session_state:
        st.session_state.lat = None
        st.session_state.lon = None
        st.session_state.weather_loaded = False
    
    # زر لجلب الموقع (لأن المتصفح يطلب إذن المستخدم)
    if st.button("📍 Détecter ma position"):
        try:
            # استخدم streamlit_js_eval لجلب الموقع
            location = streamlit_js_eval(js_expressions="navigator.geolocation.getCurrentPosition((pos) => { return pos.coords.latitude + ',' + pos.coords.longitude; })", key="gps_loc")
            if location and location != "None" and "," in location:
                st.session_state.lat, st.session_state.lon = map(float, location.split(","))
                st.success(f"📍 Localisation détectée: {st.session_state.lat:.4f}, {st.session_state.lon:.4f}")
            else:
                st.warning("⚠️ Impossible de détecter la position. Veuillez entrer votre ville manuellement.")
        except:
            st.warning("⚠️ Erreur de géolocalisation. Entrez votre ville manuellement.")
    
    # إدخال المدينة يدوياً
    city = st.text_input("🏙️ Ou entrez votre ville (ex: Alger, Oran, Constantine)")
    if city and (st.session_state.lat is None or st.button("🌐 Chercher cette ville")):
        try:
            api_key = "fd6a9aa64777078b3f7c711fb754b431"
            url = f"http://api.openweathermap.org/geo/1.0/direct?q={city}&limit=1&appid={api_key}"
            res = requests.get(url).json()
            if res:
                st.session_state.lat = res[0]["lat"]
                st.session_state.lon = res[0]["lon"]
                st.success(f"📍 Ville trouvée: {city}")
            else:
                st.error("Ville non trouvée")
        except:
            st.error("Erreur de recherche")
    
    # جلب الطقس إذا توفرت الإحداثيات
    if st.session_state.lat is not None and st.session_state.lon is not None:
        try:
            api_key = "fd6a9aa64777078b3f7c711fb754b431"
            url_weather = f"http://api.openweathermap.org/data/2.5/weather?lat={st.session_state.lat}&lon={st.session_state.lon}&appid={api_key}&units=metric"
            res_weather = requests.get(url_weather).json()
            if res_weather.get("main"):
                temp = res_weather["main"]["temp"]
                wind = res_weather["wind"]["speed"]
                description = res_weather["weather"][0]["description"]
                st.session_state.temperature = temp
                st.session_state.wind = wind
                st.session_state.weather_desc = description
                st.session_state.weather_loaded = True
            else:
                st.error("Erreur récupération météo")
        except Exception as e:
            st.error(f"Erreur: {e}")
    
    # عرض الطقس إذا تم تحميله
    if st.session_state.get("weather_loaded", False):
        col_met1, col_met2, col_met3 = st.columns(3)
        col_met1.metric("🌡️ Température", f"{st.session_state.temperature:.1f} °C")
        col_met2.metric("💨 Vent", f"{st.session_state.wind:.1f} km/h")
        col_met3.metric("🌥️ Description", st.session_state.get("weather_desc", "N/A"))
    else:
        st.info("👆 Cliquez sur 'Détecter ma position' ou entrez une ville pour voir la météo.")
    
    st.markdown("---")
    
    # =====================================================
    # أنواع البيانات (Simulation, BT, MT)
    # =====================================================
    data_mode = st.radio("Choisissez le type de données", ["🟢 Mode Simulation", "🟡 BT - Factures (PDF)", "🔵 MT - Compteurs intelligents (CSV)"])

    if data_mode == "🟢 Mode Simulation":
        if st.button("Générer données"):
            consommations = list(np.random.normal(250, 30, 50))
            voltage = float(np.random.normal(220, 5))
            current = float(np.random.normal(30, 10))
            nb_coupures_simulees = np.random.poisson(0.1, 1)[0]
            duree_heures = 50 * 24
            lambda_calculee = nb_coupures_simulees / duree_heures if duree_heures > 0 else 0.0001
            st.session_state.consommations = consommations
            st.session_state.voltage = voltage
            st.session_state.current = current
            st.session_state.lambda_panne = lambda_calculee
            # الطقس موجود بالفعل في session_state من قبل
            st.success("✅ Données simulées générées avec succès")

    elif data_mode == "🟡 BT - Factures (PDF)":
        pdf_file = st.file_uploader("Uploader facture PDF", type=["pdf"])
        coupures = st.number_input("Nombre de coupures (sur la période)", min_value=0)
        duree_heures = st.number_input("Durée totale d'observation (heures)", min_value=1, value=720)
        if st.button("Analyser facture"):
            if pdf_file:
                conso = extract_electricity_from_pdf(pdf_file)
                if conso is None:
                    st.warning("Impossible de lire la consommation.")
                else:
                    st.session_state.consommations = [conso]
                    lambda_calculee = coupures / duree_heures if duree_heures > 0 else 0.0001
                    st.session_state.lambda_panne = lambda_calculee
                    st.success(f"Consommation: {conso} kWh, λ = {lambda_calculee:.6f} panne/heure")
            else:
                st.error("Veuillez uploader un PDF.")

    elif data_mode == "🔵 MT - Compteurs intelligents (CSV)":
        csv_file = st.file_uploader("Uploader fichier CSV", type=["csv"])
        if csv_file:
            df = pd.read_csv(csv_file)
            st.dataframe(df.head())
            col_energy = st.selectbox("Colonne consommation (kWh)", df.columns)
            col_voltage = st.selectbox("Colonne tension (V)", df.columns)
            col_current = st.selectbox("Colonne courant (A)", df.columns)
            if st.button("Analyser données MT"):
                consommations = df[col_energy].dropna().tolist()
                voltage = df[col_voltage].mean()
                current = df[col_current].mean()
                if "coupure" in df.columns or "failure" in df.columns:
                    col_fail = "coupure" if "coupure" in df.columns else "failure"
                    nb_coupures = df[col_fail].sum()
                    duree_heures = len(df)
                    lambda_calculee = nb_coupures / duree_heures if duree_heures > 0 else 0.0001
                else:
                    lambda_calculee = np.std(consommations) / (np.mean(consommations) + 0.01) * 0.01
                st.session_state.consommations = consommations
                st.session_state.voltage = voltage
                st.session_state.current = current
                st.session_state.lambda_panne = lambda_calculee
                st.success(f"Données MT enregistrées. λ = {lambda_calculee:.6f}")

    # =====================================================
    # عرض البيانات الحالية مع الطقس المدمج
    # =====================================================
    if st.session_state.consommations:
        st.subheader("📊 Aperçu des données actuelles")
        st.line_chart(st.session_state.consommations)
        col_a, col_b, col_c = st.columns(3)
        col_a.metric("⚡ Taux de panne λ", f"{st.session_state.lambda_panne:.6f} /heure")
        col_b.metric("🔌 Voltage moyen", f"{st.session_state.get('voltage', 0):.1f} V")
        col_c.metric("💡 Courant moyen", f"{st.session_state.get('current', 0):.1f} A")
        # عرض الطقس مرة أخرى في الأسفل
        if st.session_state.get("weather_loaded", False):
            st.info(f"🌡️ Température actuelle: {st.session_state.temperature:.1f}°C | 💨 Vent: {st.session_state.wind:.1f} km/h")
# =========================================================
# PAGE ANALYSE CLASSIQUE
# =========================================================
elif menu == "Analyse":
    st.title("📊 Analyse des Risques (Version Statistique & IA)")

    # -------------------------------------------------
    # 1. Vérification des données d'entrée
    # -------------------------------------------------
    if "consommations" not in st.session_state or len(st.session_state["consommations"]) == 0:
        st.warning("⚠️ Aucune donnée de consommation. Veuillez d'abord charger des données dans la page 'Données'.")
        st.stop()

    consommations = st.session_state["consommations"]
    lambda_panne = st.session_state.get("lambda_panne", 0.0001) # taux de panne réel
    temp = st.session_state.get("temperature", 25.0) # température réelle
    wind = st.session_state.get("wind", 10.0) # vent réel

    # Éviter lambda nul
    if lambda_panne <= 0:
        lambda_panne = 0.0001

    # Affichage résumé
    st.subheader("📈 Résumé des données d'entrée")
    col1, col2, col3 = st.columns(3)
    col1.metric("📊 Nombre de mesures", len(consommations))
    col2.metric("⚡ Taux de panne λ", f"{lambda_panne:.6f} /h")
    col3.metric("🌡️ Température", f"{temp:.1f} °C")
    st.caption(f"💨 Vent : {wind:.1f} km/h")

    # -------------------------------------------------
    # 2. Test de normalité (Shapiro-Wilk)
    # -------------------------------------------------
    from scipy.stats import shapiro
    st.subheader("🔬 Validation des hypothèses statistiques")
    if len(consommations) >= 3:
        stat, p_value = shapiro(consommations)
        st.write(f"**Test de normalité de Shapiro-Wilk** : p-value = {p_value:.4f}")
        if p_value > 0.05:
            st.success("✅ Les données suivent une loi normale (hypothèse acceptée).")
            normal_assumption = True
        else:
            st.warning("⚠️ Les données ne suivent PAS une loi normale. Utilisation d'une méthode robuste (Bienaymé-Tchebychev).")
            normal_assumption = False
    else:
        st.warning("⚠️ Pas assez de données pour le test de normalité (minimum 3).")
        normal_assumption = False

    # -------------------------------------------------
    # 3. Calcul de P_A : probabilité de surcharge
    # -------------------------------------------------
    st.subheader("1️⃣ Probabilité de surcharge électrique")
    series = pd.Series(consommations)
    mean_val = series.mean()
    std_val = series.std() if series.std() != 0 else 1.0
    seuil = mean_val + 1.5 * std_val # seuil dynamique = moyenne + 1.5 écart-type

    if normal_assumption:
        # Loi normale : probabilité que la prochaine valeur dépasse le seuil
        predicted_value = series.iloc[-1] # dernière valeur observée
        P_A = 1 - norm.cdf(seuil, loc=predicted_value, scale=std_val)
        # Intervalle de confiance à 95% de la moyenne
        ic_low = mean_val - 1.96 * std_val / np.sqrt(len(series))
        ic_high = mean_val + 1.96 * std_val / np.sqrt(len(series))
        st.info(f"📊 **Intervalle de confiance 95% de la consommation moyenne** : [{ic_low:.1f}, {ic_high:.1f}] kWh")
    else:
        # Inégalité de Bienaymé-Tchebychev : P(|X-μ|≥kσ) ≤ 1/k²
        k = seuil / std_val if std_val > 0 else 1
        P_A = 1 / (k**2) if k > 1 else 1.0
        P_A = min(P_A, 1.0)
        st.info("⚠️ Utilisation de l'inégalité de Bienaymé-Tchebychev (sans hypothèse de normalité)")

    P_A = float(max(0, min(P_A, 1)))
    st.metric("⚡ Probabilité de dépassement du seuil", f"{P_A*100:.2f} %")
    st.caption(f"Seuil calculé : {seuil:.2f} kWh (moyenne + 1.5σ)")

    # -------------------------------------------------
    # 4. Calcul de P_B : fiabilité réseau (loi exponentielle)
    # -------------------------------------------------
    st.subheader("2️⃣ Probabilité de panne (fiabilité réseau)")
    # Probabilité d'au moins une panne dans l'heure suivante
    P_B = 1 - np.exp(-lambda_panne)
    MTBF = 1 / lambda_panne # temps moyen entre pannes (heures)
    st.metric("🔧 Probabilité de panne (dans l'heure)", f"{P_B*100:.2f} %")
    st.metric("⏱️ MTBF (Mean Time Between Failures)", f"{MTBF:.1f} heures")

    # -------------------------------------------------
    # 5. Modèle météo (Logistic Regression) - entraîné une seule fois
    # -------------------------------------------------
    st.subheader("3️⃣ Impact météo (modèle logistique)")
    # Entraînement du modèle une fois et stockage dans session_state
    if "weather_model" not in st.session_state:
        # Données d'entraînement simulées : [temp, vent] -> risque (0=faible,1=élevé)
        X_train = np.array([[25,10], [30,20], [35,30], [40,40], [45,60], [42,70]])
        y_train = np.array([0, 0, 1, 1, 1, 1])
        model_weather = LogisticRegression()
        model_weather.fit(X_train, y_train)
        st.session_state["weather_model"] = model_weather
    else:
        model_weather = st.session_state["weather_model"]

    proba_weather = model_weather.predict_proba([[temp, wind]])[0][1]
    P_C = float(max(0, min(proba_weather, 1)))
    st.metric("🌦️ Risque climatique estimé", f"{P_C*100:.2f} %")
    st.caption(f"Conditions actuelles : {temp}°C, vent {wind} km/h")

    # -------------------------------------------------
    # 6. Fusion pondérée des risques (poids modifiables)
    # -------------------------------------------------
    st.subheader("4️⃣ Calcul du risque global (fusion personnalisable)")
    col_w1, col_w2, col_w3 = st.columns(3)
    with col_w1:
        w_A = st.slider("Poids surcharge", 0.0, 1.0, 0.4, 0.05)
    with col_w2:
        w_B = st.slider("Poids fiabilité", 0.0, 1.0, 0.3, 0.05)
    with col_w3:
        w_C = st.slider("Poids météo", 0.0, 1.0, 0.3, 0.05)

    # Normalisation pour que la somme des poids = 1
    total = w_A + w_B + w_C
    if total > 0:
        w_A, w_B, w_C = w_A/total, w_B/total, w_C/total

    Risk = w_A * P_A + w_B * P_B + w_C * P_C
    Risk = float(max(0, min(Risk, 1)))
    st.metric("🎯 **Indice de Risque Global**", f"{Risk*100:.2f} %")

    # -------------------------------------------------
    # 7. Niveau de risque et interprétation
    # -------------------------------------------------
    if Risk < 0.4:
        st.success("🟢 **Niveau Faible** – Aucune action immédiate requise")
    elif Risk < 0.7:
        st.warning("🟠 **Niveau Moyen** – Surveillance renforcée recommandée")
    else:
        st.error("🔴 **Niveau Élevé** – Intervention nécessaire")

    # -------------------------------------------------
    # 8. Graphique comparatif des probabilités
    # -------------------------------------------------
    fig, ax = plt.subplots()
    ax.bar(["Surcharge", "Fiabilité", "Météo"], [P_A, P_B, P_C],
           color=['#1f77b4', '#ff7f0e', '#2ca02c'])
    ax.set_ylabel("Probabilité")
    ax.set_title("Comparaison des facteurs de risque")
    ax.set_ylim(0, 1)
    for i, v in enumerate([P_A, P_B, P_C]):
        ax.text(i, v + 0.02, f"{v*100:.1f}%", ha='center')
    st.pyplot(fig)

    # -------------------------------------------------
    # 9. Sauvegarde des résultats pour les autres pages
    # -------------------------------------------------
    st.session_state["risk_final"] = Risk * 100
    st.session_state["P_A"] = P_A
    st.session_state["P_B"] = P_B
    st.session_state["P_C"] = P_C
    st.session_state["lambda_used"] = lambda_panne

    # -------------------------------------------------
    # 10. (Optionnel) Explication des formules mathématiques
    # -------------------------------------------------
    with st.expander("📐 Voir les détails mathématiques"):
        st.markdown(r"""
        **1. Probabilité de surcharge**  
        - Hypothèse normale : $P_A = 1 - \Phi\left(\frac{S - \hat{x}_{t+1}}{\sigma}\right)$ où $\Phi$ est la fonction de répartition de la loi normale.  
        - Sinon : Inégalité de Bienaymé-Tchebychev $P(|X-\mu|\ge k\sigma) \le \frac{1}{k^2}$.

        **2. Probabilité de panne (fiabilité)**  
        - Loi exponentielle : $P_B = 1 - e^{-\lambda t}$ avec $t=1$ heure.

        **3. Impact météo**  
        - Régression logistique : $P_C = \frac{1}{1+e^{-(\beta_0 + \beta_1 T + \beta_2 V)}}$.

        **4. Risque global**  
        - $R = w_A P_A + w_B P_B + w_C P_C$, avec $w_i$ personnalisables.
        """)
 # =========================================================
# PAGE PRÉVISION
elif menu == "Prévision":
    st.title("⚡ Prévision intelligente de la consommation et des coupures")

    # -------------------------------------------------
    # 1. Vérification des données
    # -------------------------------------------------
    if "consommations" not in st.session_state or len(st.session_state["consommations"]) < 5:
        st.warning("⚠️ Pas assez de données. Veuillez d'abord charger des données dans la page 'Données'.")
        st.stop()

    consommations = st.session_state["consommations"]
    temperature = st.session_state.get("temperature", 20.0)
    vent = st.session_state.get("wind", 10.0)
    lambda_panne = st.session_state.get("lambda_panne", 0.0001)

    # Création d'un DataFrame avec historique
    dates = pd.date_range(end=datetime.today(), periods=len(consommations), freq='D')
    df = pd.DataFrame({
        "date": dates,
        "consommation": consommations,
        "temp": temperature,
        "vent": vent
    })
    df.set_index("date", inplace=True)

    # -------------------------------------------------
    # 2. Graphique de l'historique + tendance simple
    # -------------------------------------------------
    st.subheader("📊 Votre consommation électrique récente")
    st.line_chart(df["consommation"])

    # Tendance en langage clair
    moyenne = df["consommation"].mean()
    derniere = df["consommation"].iloc[-1]
    if derniere > moyenne * 1.1:
        tendance = "🔺 **en hausse** : vous consommez plus que d'habitude."
    elif derniere < moyenne * 0.9:
        tendance = "🔻 **en baisse** : vous consommez moins que d'habitude."
    else:
        tendance = "➡️ **stable** : votre consommation est dans la normale."
    st.info(f"📌 Tendance actuelle : {tendance}")

    # -------------------------------------------------
    # 3. Prévision de la consommation (ARIMA) + explication
    # -------------------------------------------------
    st.subheader("🔮 Prévision de votre consommation pour les prochains jours")
    jours = st.slider("Nombre de jours à prévoir", 3, 14, 7)

    try:
        from statsmodels.tsa.arima.model import ARIMA
        model = ARIMA(df["consommation"], order=(1,1,1))
        model_fit = model.fit()
        prevision = model_fit.forecast(steps=jours)

        # Tableau des prévisions
        dates_futur = pd.date_range(start=df.index[-1] + timedelta(days=1), periods=jours, freq='D')
        df_prev = pd.DataFrame({
            "Date": dates_futur.strftime("%d/%m/%Y"),
            "Consommation prévue (kWh)": prevision.round(1)
        })
        st.table(df_prev)

        # Graphique historique + prévision
        fig, ax = plt.subplots()
        ax.plot(df.index, df["consommation"], label="Historique", color='blue')
        ax.plot(dates_futur, prevision, label="Prévision", color='red', marker='o')
        ax.set_title("Évolution de la consommation (réelle et prévue)")
        ax.legend()
        st.pyplot(fig)

        # Explication simple
        variation = (prevision.iloc[-1] - df["consommation"].iloc[-1]) / df["consommation"].iloc[-1] * 100
        if variation > 10:
            st.warning(f"⚠️ Votre consommation devrait **augmenter de {variation:.1f}%** dans les {jours} jours. Pensez à réduire les appareils énergivores.")
        elif variation < -10:
            st.success(f"✅ Bonne nouvelle : votre consommation devrait **baisser de {abs(variation):.1f}%**.")
        else:
            st.info(f"📉 La consommation restera **stable** (variation de {variation:.1f}%).")
    except Exception as e:
        st.error(f"Erreur lors de la prévision ARIMA : {e}")
        st.info("💡 Astuce : essayez avec au moins 10 valeurs de consommation dans 'Données'.")

    # -------------------------------------------------
    # 4. Prévision des coupures (IA + météo + historique)
    # -------------------------------------------------
    st.subheader("⚠️ Risque de coupure électrique dans les prochaines 24h")
    st.markdown("Notre système analyse votre **charge électrique**, la **météo** et l'**historique des pannes**.")

    # Simuler un historique de pannes (si pas déjà en session)
    if "historique_pannes" not in st.session_state:
        dates_pannes = pd.date_range(start=datetime.today() - timedelta(days=60), periods=8, freq='7D')
        st.session_state["historique_pannes"] = pd.DataFrame({
            "date": dates_pannes,
            "duree (min)": np.random.randint(10, 180, 8),
            "cause": np.random.choice(["Surcharge", "Tempête", "Équipement", "Foudre"], 8)
        })
    df_pannes = st.session_state["historique_pannes"]

    with st.expander("📋 Historique des dernières coupures"):
        st.dataframe(df_pannes.tail(5))

    # Calcul du risque
    conso_actuelle = df["consommation"].iloc[-1]
    seuil_charge = df["consommation"].mean() * 1.2
    charge_elevee = conso_actuelle > seuil_charge
    conditions_meteo_risque = (temperature > 35) or (vent > 45)

    # Probabilité de base à partir de l'historique (derniers 30 jours)
    pannes_recentes = df_pannes[df_pannes["date"] > datetime.today() - timedelta(days=30)]
    if len(pannes_recentes) > 0:
        proba_hist = len(pannes_recentes) / 30
    else:
        proba_hist = 0.03 # 3% par défaut

    # Ajustement selon charge et météo
    if charge_elevee and conditions_meteo_risque:
        proba_risque = min(proba_hist * 4, 0.95)
        message = "🔴 **Risque très élevé** : forte consommation + conditions météo défavorables (chaleur ou vent fort)."
    elif charge_elevee or conditions_meteo_risque:
        proba_risque = min(proba_hist * 2, 0.70)
        message = "🟠 **Risque modéré** : soit la charge est élevée, soit la météo est mauvaise."
    else:
        proba_risque = proba_hist * 0.8
        message = "🟢 **Risque faible** : situation normale."

    # Intégrer le taux de panne λ (loi exponentielle)
    proba_lambda = 1 - np.exp(-lambda_panne * 24)
    proba_finale = 0.6 * proba_risque + 0.4 * proba_lambda
    proba_finale = min(proba_finale, 0.99)

    st.metric("📊 Probabilité de coupure dans les 24h", f"{proba_finale*100:.1f}%")
    st.info(message)

    # -------------------------------------------------
    # 5. Conseils pratiques (langage simple)
    # -------------------------------------------------
    st.subheader("💡 Que faire maintenant ?")
    if proba_finale > 0.6:
        st.error("""
        **Actions recommandées :**
        - Réduisez immédiatement l'usage des appareils puissants (climatiseurs, machines industrielles).
        - Préparez un groupe électrogène ou une batterie de secours.
        - Contactez votre fournisseur d'électricité si la situation persiste.
        """)
    elif proba_finale > 0.3:
        st.warning("""
        **Précautions :**
        - Surveillez votre consommation chaque heure.
        - Évitez de lancer plusieurs gros appareils en même temps.
        - Vérifiez l'état de vos installations électriques.
        """)
    else:
        st.success("""
        **Situation stable :**
        - Vous pouvez travailler normalement.
        - Continuez à surveiller votre consommation une fois par jour.
        """)

    # -------------------------------------------------
    # 6. Détail technique optionnel (pour les curieux)
    # -------------------------------------------------
    with st.expander("🔧 Pour en savoir plus (modèles utilisés)"):
        st.markdown("""
        - **ARIMA** : modèle statistique qui analyse les tendances passées pour prévoir la consommation future.
        - **Loi exponentielle** : calcule la probabilité de panne à partir du taux de panne λ (nombre de pannes par heure).
        - **Règle météo** : si température > 35°C ou vent > 45 km/h, le risque augmente.
        - **Historique** : plus il y a eu de coupures récentes, plus le risque est élevé.
        """)
# =========================================================
# PAGE RAPPORT (corrigée et améliorée)
# =========================================================
elif menu == "Rapport":
    st.title("📄 Rapport Intelligent - Analyse des Risques")

    # --- Vérifier que l'analyse a été faite ---
    if "risk_final" not in st.session_state:
        st.warning("⚠️ Veuillez d'abord effectuer l'analyse du risque dans la page 'Analyse'.")
        st.stop()

    # --- Récupération des données depuis session_state ---
    risk_percent = float(st.session_state.get("risk_final", 50.0))
    risk = risk_percent / 100.0
    P_A = float(st.session_state.get("P_A", 0.2))
    P_B = float(st.session_state.get("P_B", 0.2))
    P_C = float(st.session_state.get("P_C", 0.2))
    consommations = st.session_state.get("consommations", [])
    lambda_panne = st.session_state.get("lambda_panne", 0.0001)
    temperature = st.session_state.get("temperature", 25.0)
    wind = st.session_state.get("wind", 10.0)

    # --- Détermination du niveau de risque (simple) ---
    if risk_percent < 40:
        niveau = "🟢 Faible"
        zone = "Zone Verte – Exploitation normale"
        couleur = "success"
    elif risk_percent < 70:
        niveau = "🟠 Moyen"
        zone = "Zone Orange – Surveillance renforcée"
        couleur = "warning"
    else:
        niveau = "🔴 Élevé"
        zone = "Zone Rouge – Risque critique"
        couleur = "error"

    # --- 1. Résumé exécutif ---
    st.subheader("📌 1. Résumé exécutif")
    resume = f"""
    Le niveau global de risque du réseau électrique est estimé à **{risk_percent:.1f}%**, ce qui correspond à un niveau **{niveau}**.  
    Cette évaluation combine :
    - La probabilité de surcharge (P_A = {P_A*100:.1f}%)
    - La probabilité de panne (P_B = {P_B*100:.1f}%)
    - L'impact météo (P_C = {P_C*100:.1f}%)
    """
    st.info(resume)

    # --- 2. Degré de criticité ---
    st.subheader("⚠️ 2. Degré de criticité du réseau")
    if couleur == "success":
        st.success(zone)
    elif couleur == "warning":
        st.warning(zone)
    else:
        st.error(zone)

    # --- 3. Impact technique sur les équipements ---
    st.subheader("🔧 3. Impact technique sur les équipements")
    impact_text = """
    - **Transformateurs** : Risque d'échauffement thermique accru (surcharge ou température élevée).
    - **Lignes électriques** : Dilatation des conducteurs et perte de rendement.
    - **Protections** : Possibilité de déclenchement intempestif si les seuils sont mal réglés.
    - **Continuité de service** : Probabilité d'interruption augmentée en cas de panne réseau.
    """
    st.write(impact_text)

    # --- 4. Analyse des facteurs de risque (sans Random Forest) ---
    st.subheader("📊 4. Analyse des facteurs de risque")
    # Déterminer le facteur dominant
    facteurs = {"Surcharge": P_A, "Fiabilité": P_B, "Météo": P_C}
    dominant = max(facteurs, key=facteurs.get)
    st.write(f"**Facteur dominant** : **{dominant}** (probabilité = {facteurs[dominant]*100:.1f}%)")

    # Graphique des probabilités
    fig, ax = plt.subplots()
    ax.bar(["Surcharge", "Fiabilité", "Météo"], [P_A, P_B, P_C], color=['#1f77b4', '#ff7f0e', '#2ca02c'])
    ax.set_ylabel("Probabilité")
    ax.set_title("Comparaison des facteurs de risque")
    ax.set_ylim(0, 1)
    for i, v in enumerate([P_A, P_B, P_C]):
        ax.text(i, v + 0.02, f"{v*100:.1f}%", ha='center')
    st.pyplot(fig)

    # --- 5. Scénarios prospectifs ---
    st.subheader("🔮 5. Scénarios prospectifs")
    scenario_text = f"""
    - **Scénario 1 – Maintien de la tendance actuelle** :  
      Le risque restera autour de {risk_percent:.1f}%. Une augmentation de la consommation ou une canicule pourrait le faire grimper.

    - **Scénario 2 – Maintenance préventive renforcée** :  
      Réduction du taux de panne λ de 20% → baisse du risque d'environ {0.2*P_B*100:.1f} points de pourcentage.

    - **Scénario 3 – Installation de capacités solaires/batteries** :  
      Réduction de la pointe de consommation → baisse du risque de surcharge, amélioration globale.
    """
    st.write(scenario_text)

    # --- 6. Décision ingénierie recommandée ---
    st.subheader("🛠️ 6. Décision d'ingénierie recommandée")
    decision_text = f"""
    Sur la base des analyses, une intervention ciblée sur le facteur **{dominant}** est prioritaire.
    """
    if dominant == "Surcharge":
        decision_text += """
        - Installer une solution de **peak shaving** (solaire + batteries) ou décaler les charges.
        - Renforcer la capacité du transformateur si le taux de charge dépasse 80%.
        """
    elif dominant == "Fiabilité":
        decision_text += """
        - Mettre en place une **maintenance préventive** systématique.
        - Installer une redondance (UPS, groupes électrogènes) pour les charges critiques.
        """
    else:
        decision_text += """
        - Améliorer la **ventilation** des locaux techniques.
        - Surveiller les prévisions météo et anticiper les pics de chaleur.
        """
    st.write(decision_text)

    # --- 7. Génération du rapport PDF ---
    st.subheader("📑 7. Exporter le rapport")
    if st.button("Générer le rapport technique (PDF)"):
        try:
            import tempfile
            from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
            from reportlab.lib.styles import getSampleStyleSheet
            from reportlab.lib.pagesizes import A4

            pdf_file = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf")
            doc = SimpleDocTemplate(pdf_file.name, pagesize=A4)
            elements = []
            styles = getSampleStyleSheet()

            elements.append(Paragraph("PowerRisk – Rapport Technique d'Évaluation du Risque", styles["Title"]))
            elements.append(Spacer(1, 20))
            elements.append(Paragraph(resume, styles["Normal"]))
            elements.append(Spacer(1, 20))
            elements.append(Paragraph(f"**{zone}**", styles["Normal"]))
            elements.append(Spacer(1, 20))
            elements.append(Paragraph("Impact Technique :", styles["Heading2"]))
            elements.append(Paragraph(impact_text, styles["Normal"]))
            elements.append(Spacer(1, 20))
            elements.append(Paragraph(f"Facteur dominant : {dominant}", styles["Normal"]))
            elements.append(Paragraph(decision_text, styles["Normal"]))

            doc.build(elements)

            with open(pdf_file.name, "rb") as f:
                st.download_button(
                    label="Télécharger le rapport (PDF)",
                    data=f,
                    file_name="PowerRisk_Rapport.pdf",
                    mime="application/pdf",
                )
            os.unlink(pdf_file.name)
        except Exception as e:
            st.error(f"Erreur lors de la génération du PDF : {e}")

# =========================================================
# PAGE SOLUTIONS (Version Complète avec Chatbot IA)
# =========================================================
# =========================================================
# PAGE SOLUTIONS (Version avec clé API intégrée - sans saisie)
# =========================================================
elif menu == "Solutions":
    st.title("🛠 Solutions Recommandées - Analyse & Décision")

    # ------------------ Définition de la fonction VAN/ROI ------------------
    def calcul_van_roi(investissement, flux_annuel, taux, annees):
        if investissement <= 0:
            return 0.0, 0.0
        van = -investissement
        for t in range(1, annees + 1):
            van += flux_annuel / ((1 + taux) ** t)
        roi = investissement / flux_annuel if flux_annuel > 0 else float('inf')
        return van, roi

    # --- Vérification des données ---
    if "risk_final" not in st.session_state:
        st.warning("⚠️ Veuillez d'abord effectuer l'analyse du risque (page 'Analyse').")
        st.stop()

    # --- Récupération des données ---
    risk = float(st.session_state.get("risk_final", 50.0))
    P_A = float(st.session_state.get("P_A", 0.2))
    P_B = float(st.session_state.get("P_B", 0.2))
    P_C = float(st.session_state.get("P_C", 0.2))
    consommations = st.session_state.get("consommations", [250, 260, 240, 270, 255])
    lambda_panne = float(st.session_state.get("lambda_panne", 0.0001))
    temp = float(st.session_state.get("temperature", 25.0))
    wind = st.session_state.get("wind", 10.0)
    secteur = st.session_state.get("secteur_activite", "Industrie")

    if lambda_panne <= 0:
        lambda_panne = 0.0001

    # ---------- 1. ANALYSE DE LA DEMANDE DE POINTE ----------
    st.header("📈 1. Analyse de la demande de pointe")
    peak_demand_kw = max(consommations)
    avg_consumption_kw = np.mean(consommations)
    st.info(f"💡 **Pic de consommation** : `{peak_demand_kw:.2f} kWh` | **Moyenne** : `{avg_consumption_kw:.2f} kWh`")

    col1, col2 = st.columns(2)
    with col1:
        peak_hours = st.number_input("⏱️ Durée de la pointe (heures)", 1, 8, 3)
    with col2:
        peak_coverage = st.slider("🎯 Couverture souhaitée (%)", 0, 100, 75)

    extra_energy_needed = max(0, (peak_demand_kw - avg_consumption_kw)) * peak_hours
    target_energy_kwh = extra_energy_needed * (peak_coverage / 100.0)

    if target_energy_kwh <= 0:
        st.success("✅ Votre consommation est stable. Aucune capacité supplémentaire nécessaire.")
    else:
        st.warning(f"⚠️ Énergie cible à fournir pendant la pointe : **{target_energy_kwh:.2f} kWh**")

        # ---------- 2. SIMULATION ÉCONOMIQUE & COMPARAISON ----------
        st.header("💰 2. Simulation économique : comparaison des solutions")
        
        with st.expander("🔧 Paramètres économiques"):
            prix_kwh = st.number_input("💵 Prix du kWh (DZD)", 5, 30, 8)
            taux_actualisation = st.slider("📉 Taux d'actualisation (%)", 0, 15, 8) / 100.0
            duree_projet = st.slider("📅 Durée du projet (années)", 5, 25, 15)

        # ---- Solution Solaire ----
        with st.expander("☀️ Solution 1 : Solaire photovoltaïque"):
            irradiation = st.number_input("☀️ Ensoleillement (kWh/m²/jour)", 2.0, 7.0, 5.0, 0.1)
            panel_power = st.selectbox("Puissance crête par panneau (Wc)", [400, 450, 500, 550], index=2)
            cout_panneau = st.number_input("💰 Coût par panneau (DZD)", 15000, 60000, 25000)
            efficiency = st.slider("⚙️ Efficacité système (%)", 50, 95, 75) / 100.0
            
            prod_journaliere_panel = (panel_power / 1000) * irradiation * efficiency
            nb_panneaux = int(np.ceil(target_energy_kwh / prod_journaliere_panel)) if prod_journaliere_panel > 0 else 0
            invest_solaire = nb_panneaux * cout_panneau
            prod_annuelle_kwh = nb_panneaux * prod_journaliere_panel * 365
            econ_annuelle_solaire = prod_annuelle_kwh * prix_kwh
            VAN_solaire, ROI_solaire = calcul_van_roi(invest_solaire, econ_annuelle_solaire, taux_actualisation, duree_projet)

        # ---- Solution Batterie ----
        with st.expander("🔋 Solution 2 : Batterie de stockage"):
            cout_batterie_par_kwh = st.number_input("💰 Coût batterie (DZD/kWh utile)", 30000, 150000, 70000)
            duree_vie_batterie = st.slider("🔋 Durée de vie batterie (ans)", 5, 15, 10)
            depth_discharge = st.slider("Profondeur de décharge utile (%)", 50, 95, 80) / 100.0
            
            capacite_utile_kwh = target_energy_kwh / depth_discharge
            invest_batterie = capacite_utile_kwh * cout_batterie_par_kwh
            econ_annuelle_batterie = target_energy_kwh * prix_kwh * 365
            VAN_batterie, ROI_batterie = calcul_van_roi(invest_batterie, econ_annuelle_batterie, taux_actualisation, min(duree_projet, duree_vie_batterie))

        # ---- Solution Hybride ----
        with st.expander("⚡ Solution 3 : Système hybride (Solaire + Batterie)"):
            part_solaire = st.slider("Part solaire (%)", 0, 100, 60) / 100.0
            part_batterie = 1 - part_solaire
            energie_solaire = target_energy_kwh * part_solaire
            energie_batterie = target_energy_kwh * part_batterie
            
            nb_panneaux_hyb = int(np.ceil(energie_solaire / prod_journaliere_panel)) if prod_journaliere_panel>0 else 0
            invest_solaire_hyb = nb_panneaux_hyb * cout_panneau
            capacite_batterie_hyb = (energie_batterie / depth_discharge) if depth_discharge>0 else 0
            invest_batterie_hyb = capacite_batterie_hyb * cout_batterie_par_kwh
            invest_hybride = invest_solaire_hyb + invest_batterie_hyb
            econ_annuelle_hybride = (energie_solaire + energie_batterie) * prix_kwh * 365
            VAN_hybride, ROI_hybride = calcul_van_roi(invest_hybride, econ_annuelle_hybride, taux_actualisation, duree_projet)

        # ---- Tableau comparatif ----
        st.subheader("📊 Comparaison des solutions")
        df_comparaison = pd.DataFrame({
            "Solution": ["Solaire", "Batterie", "Hybride"],
            "Investissement (DZD)": [invest_solaire, invest_batterie, invest_hybride],
            "Économie annuelle (DZD)": [econ_annuelle_solaire, econ_annuelle_batterie, econ_annuelle_hybride],
            "VAN (DZD)": [VAN_solaire, VAN_batterie, VAN_hybride],
            "ROI (années)": [ROI_solaire, ROI_batterie, ROI_hybride]
        })
        for col in ["Investissement (DZD)", "Économie annuelle (DZD)", "VAN (DZD)"]:
            df_comparaison[col] = df_comparaison[col].round(0).astype(int)
        df_comparaison["ROI (années)"] = df_comparaison["ROI (années)"].round(1)
        st.dataframe(df_comparaison, use_container_width=True)

        meilleure = df_comparaison.loc[df_comparaison["VAN (DZD)"].idxmax()]
        st.success(f"🏆 **Solution la plus rentable** : {meilleure['Solution']} avec une VAN de {meilleure['VAN (DZD)']:,} DZD et un ROI de {meilleure['ROI (années)']} ans.")

        # ---------- 3. SOLUTIONS DYNAMIQUES (TIME-OF-USE) ----------
        st.header("⏰ 3. Optimisation temporelle (Time-of-Use)")
        st.markdown("Analyse des heures de pointe et suggestion de décalage des charges.")

        if "consommation_horaire" not in st.session_state:
            heures = list(range(24))
            charge = [20 + 15 * np.sin(np.pi * (h - 12) / 12)**2 for h in heures]
            charge = [c + np.random.normal(0, 2) for c in charge]
            st.session_state.consommation_horaire = pd.DataFrame({"Heure": heures, "kWh": charge})
        df_horaire = st.session_state.consommation_horaire
        
        fig_heat, ax_heat = plt.subplots(figsize=(10, 3))
        ax_heat.bar(df_horaire["Heure"], df_horaire["kWh"], color='skyblue')
        ax_heat.set_xlabel("Heure")
        ax_heat.set_ylabel("Consommation (kWh)")
        ax_heat.set_title("Profil de consommation horaire type")
        st.pyplot(fig_heat)

        seuil_pointe = df_horaire["kWh"].quantile(0.75)
        heures_pointe = df_horaire[df_horaire["kWh"] > seuil_pointe]["Heure"].tolist()
        st.warning(f"⏳ Heures de pointe détectées : {heures_pointe}")
        st.info("💡 **Recommandation dynamique** : Déplacez les processus énergivores vers les heures creuses (ex: 22h-6h). Utilisez un programmateur ou un EMS.")

        # ---------- 4. CHATBOT IA (AVEC CLÉ INTÉGRÉE) ---------- pu être initialisée.")
        # ---------- 4. CHATBOT IA (Gemini gratuit) ----------
        st.header("🤖 4. Assistant IA - Posez vos questions")

# مفتاح Gemini المجاني (استبدله بمفتاحك الحقيقي)
        GEMINI_API_KEY = "AIzaSyA6OEjzOfg5LxOS4Nb9XWF174SZvvOGTTk" # ⬅️ ضع المفتاح هنا

# Gestion de l'état du chat
        if "chat_open" not in st.session_state:
           st.session_state.chat_open = False
        if "messages" not in st.session_state:
           st.session_state.messages = []

        if st.button("💬 Ouvrir le chat IA", use_container_width=True):
           st.session_state.chat_open = not st.session_state.chat_open

        if st.session_state.chat_open:
           with st.container():
                st.markdown("---")
                st.markdown("#### 💬 Assistant PowerRisk")
        
        # Initialiser Gemini
                try:
                    genai.configure(api_key=GEMINI_API_KEY)
                    model = genai.GenerativeModel('gemini-1.5-flash')
                    api_ok = True
                except ImportError:
                    st.error("❌ Bibliothèque manquante: exécutez 'pip install google-generativeai'")
                    api_ok = False
                except Exception as e:
                    st.error(f"❌ Erreur API: {e}")
                    api_ok = False

                if api_ok:
            # Afficher les messages précédents
                   for msg in st.session_state.messages:
                       with st.chat_message(msg["role"]):
                           st.markdown(msg["content"])

            # Zone de saisie
                   user_input = st.chat_input("Posez une question sur les résultats ou les solutions...")
                   if user_input:
                      st.session_state.messages.append({"role": "user", "content": user_input})
                      with st.chat_message("user"):
                          st.markdown(user_input)

                # Contexte enrichi
                      contexte = f"""
                     Tu es un expert en efficacité énergétique. Voici les données du client :
                    - Secteur : {secteur}
                    - Consommation moyenne : {avg_consumption_kw:.1f} kWh
                    - Pic de consommation : {peak_demand_kw:.1f} kWh
                    - Taux de panne λ : {lambda_panne:.6f}
                    - Température : {temp}°C, Vent : {wind} km/h
                    - Risque global : {risk:.1f}%
                    - Solutions proposées : Solaire (VAN={VAN_solaire:.0f} DZD, ROI={ROI_solaire:.1f} ans), Batterie (VAN={VAN_batterie:.0f} DZD), Hybride (VAN={VAN_hybride:.0f} DZD)
                    - Meilleure solution : {meilleure['Solution']}
                    - Heures de pointe : {heures_pointe}
                     Réponds en français de manière claire et utile.
                """
                
                      try:
                           response = model.generate_content(f"{contexte}\n\nQuestion de l'utilisateur: {user_input}")
                           assistant_reply = response.text
                      except Exception as e:
                           assistant_reply = f"❌ Erreur: {e}"

                           st.session_state.messages.append({"role": "assistant", "content": assistant_reply})
                           with st.chat_message("assistant"):
                             st.markdown(assistant_reply)

            # Bouton effacer
                if st.button("🗑️ Effacer la conversation"):
                    st.session_state.messages = []
                    st.rerun()

        # ---------- 5. PLAN D'ACTION FINAL ----------
        st.header("✅ Plan d'action prioritaire")
        facteurs = {"Surcharge": P_A, "Fiabilité": P_B, "Météo": P_C}
        dominant = max(facteurs, key=facteurs.get)
        if dominant == "Surcharge":
            st.success("Priorité : **Réduction de la pointe** via solaire/batterie + décalage des charges.")
        elif dominant == "Fiabilité":
            st.info("Priorité : **Maintenance préventive** et redondance (UPS, groupes électrogènes).")
        else:
            st.warning("Priorité : **Renforcement face au climat** (ventilation, isolation, stockage).")

        st.write("---")
        st.caption("Analyse générée par PowerRisk – recommandations basées sur les données et l'intelligence artificielle.")
