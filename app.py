# =========================================================
# IMPORTS
# =========================================================
import streamlit as st
import pandas as pd
import numpy as np
import pdfplumber
import re
import requests
import matplotlib.pyplot as plt
import bcrypt
import random
import smtplib
import tempfile
import os
from statsmodels.tsa.arima.model import ARIMA
from sklearn.ensemble import RandomForestRegressor
from sklearn.naive_bayes import GaussianNB
from sklearn.linear_model import LogisticRegression
from streamlit_js_eval import streamlit_js_eval
from email.mime.text import MIMEText
from datetime import datetime, timedelta
from scipy.stats import norm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.pagesizes import A4
from pymongo import MongoClient
from bson.objectid import ObjectId
import plotly.express as px
import plotly.graph_objects as go
import google.generativeai as genai

# =========================================================
# DATABASE (MongoDB Atlas)
# =========================================================

MONGO_URI = "mongodb+srv://powerrisk:powerrisk22ps@cluster0.rkxgkti.mongodb.net/powerrisk?retryWrites=true&w=majority"

client = MongoClient(MONGO_URI)
db = client["powerrisk"]

users_col = db["users"]
entreprises_col = db["entreprises"]
points_col = db["points"]
subscriptions_col = db["subscriptions"]

# =========================================================
# ADMIN FUNCTIONS
# =========================================================

def init_admin():
    """Crée le compte administrateur spécifique s'il n'existe pas"""
    admin_email = "ouafiyousraps@gmail.com"
    admin_user = users_col.find_one({"email": admin_email})
    if not admin_user:
        hashed = bcrypt.hashpw("Admin123".encode(), bcrypt.gensalt()).decode()
        admin_data = {
            "nom_complet": "Administrateur",
            "email": admin_email,
            "mot_de_passe": hashed,
            "is_verified": 1,
            "verification_code": None,
            "reset_code": None,
            "is_admin": 1,
            "created_at": datetime.now()
        }
        users_col.insert_one(admin_data)
        print(f"✅ Compte admin créé : {admin_email}")
    else:
        users_col.update_one({"email": admin_email}, {"$set": {"is_admin": 1}})

def is_admin_user(user_id):
    """Vérifie si l'utilisateur est administrateur"""
    try:
        if isinstance(user_id, str):
            user_id = ObjectId(user_id)
        user = users_col.find_one({"_id": user_id})
        return user and user.get("is_admin", 0) == 1
    except:
        return False

# Initialisation du compte admin
init_admin()

# =========================================================
# FONCTIONS D'AUTHENTIFICATION (MongoDB)
# =========================================================

def register_user(data):
    email = data["email"].lower().strip()
    if users_col.find_one({"email": email}):
        return "EMAIL_EXISTS"
    
    # Premier utilisateur devient admin
    user_count = users_col.count_documents({})
    is_admin = 1 if user_count == 0 else 0
    
    hashed = bcrypt.hashpw(data["password"].encode(), bcrypt.gensalt()).decode()
    code = str(random.randint(100000, 999999))
    
    user = {
        "nom_complet": data["nom"],
        "email": email,
        "mot_de_passe": hashed,
        "verification_code": code,
        "is_verified": 0,
        "reset_code": None,
        "is_admin": is_admin,
        "created_at": datetime.now()
    }
    user_id = users_col.insert_one(user).inserted_id
    
    entreprise = {
        "user_id": user_id,
        "nom_entreprise": data["nom_entreprise"],
        "secteur_activite": data["secteur"],
        "taille_entreprise": data["taille"],
        "wilaya": data["wilaya"],
        "email_professionnel": email,
        "type_installation": data["type_installation"],
        "puissance_installee_kva": data["puissance"],
        "consommation_moyenne_kwh": data["consommation"],
        "nombre_coupures_mois": data["coupures"],
        "numero_telephone": data["telephone"],
        "temperature_moyenne_regionale": data["temperature"],
        "objectif_utilisation": data["objectif"],
        "energie_alternative": data["energie_alt"],
        "etat_equipements": data["etat"],
        "frequence_maintenance": data["maintenance"],
        "dernier_incident": str(data["incident"]),
        "type_contrat_assurance": data["contrat"],
        "created_at": datetime.now()
    }
    entreprises_col.insert_one(entreprise)
    
    points = {
        "user_id": user_id,
        "total_points": 20,
        "used_points": 0,
        "created_at": datetime.now()
    }
    points_col.insert_one(points)
    
    from datetime import date
    subscription = {
        "user_id": user_id,
        "plan": "TRIAL",
        "start_date": str(date.today()),
        "end_date": None,
        "status": "active",
        "created_at": datetime.now()
    }
    subscriptions_col.insert_one(subscription)
    
    send_email(email, "Bienvenue sur PowerRisk", code, is_welcome=True, user_name=data["nom"])
    return "SUCCESS"

def verify_account(email, code):
    email = email.lower().strip()
    user = users_col.find_one({"email": email, "verification_code": code})
    if not user:
        return None
    users_col.update_one({"_id": user["_id"]}, {"$set": {"is_verified": 1, "verification_code": None}})
    return str(user["_id"])

def login_user(email, password):
    email = email.lower().strip()
    user = users_col.find_one({"email": email})
    if not user:
        return None
    if not user.get("is_verified"):
        return "NOT_VERIFIED"
    if not bcrypt.checkpw(password.encode(), user["mot_de_passe"].encode()):
        return None
    return str(user["_id"])

def forgot_password(email):
    email = email.lower().strip()
    user = users_col.find_one({"email": email})
    if not user:
        return False
    code = str(random.randint(100000, 999999))
    users_col.update_one({"_id": user["_id"]}, {"$set": {"reset_code": code}})
    body = f"Votre code de réinitialisation PowerRisk est : {code}"
    send_email(email, "Réinitialisation mot de passe PowerRisk", body, is_welcome=False)
    return True

def reset_password(email, code, new_password):
    email = email.lower().strip()
    user = users_col.find_one({"email": email, "reset_code": code})
    if not user:
        return False
    hashed = bcrypt.hashpw(new_password.encode(), bcrypt.gensalt()).decode()
    users_col.update_one({"_id": user["_id"]}, {"$set": {"mot_de_passe": hashed, "reset_code": None}})
    return True

def get_points(user_id):
    try:
        if isinstance(user_id, str):
            user_id = ObjectId(user_id)
        pts = points_col.find_one({"user_id": user_id})
        if not pts:
            return 0
        return pts["total_points"] - pts.get("used_points", 0)
    except Exception as e:
        print(f"Erreur get_points: {e}")
        return 0

def use_points(user_id):
    try:
        if isinstance(user_id, str):
            user_id = ObjectId(user_id)
        
        # Vérifier abonnement illimité
        sub = subscriptions_col.find_one({"user_id": user_id})
        if sub and sub.get("plan") in ["MONTHLY", "YEARLY"]:
            expiry = sub.get("expiry_date")
            if expiry and isinstance(expiry, str):
                expiry = datetime.fromisoformat(expiry)
            if expiry and expiry > datetime.now():
                return True
        
        if get_points(user_id) < 5:
            return False
        
        points_col.update_one(
            {"user_id": user_id},
            {"$inc": {"used_points": 5}}
        )
        return True
    except Exception as e:
        print(f"Erreur use_points: {e}")
        return False

def can_access_page(user_id):
    try:
        if isinstance(user_id, str):
            user_id = ObjectId(user_id)
        
        sub = subscriptions_col.find_one({"user_id": user_id})
        if sub and sub.get("plan") in ["MONTHLY", "YEARLY"]:
            expiry = sub.get("expiry_date")
            if expiry and isinstance(expiry, str):
                expiry = datetime.fromisoformat(expiry)
            if expiry and expiry > datetime.now():
                return True, "unlimited"
        
        points = get_points(user_id)
        if points >= 5:
            return True, "points"
        else:
            return False, points
    except Exception as e:
        print(f"Erreur can_access_page: {e}")
        return False, 0

# =========================================================
# EMAIL
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
        - Recevoir des solutions personnalisées
        - Gagner des points à chaque action
        Votre code de vérification est : {body}
        Cordialement, L'équipe PowerRisk
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
# EXTRACTION PDF
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
        return None
    except:
        return None

# =========================================================
# LSTM MODEL (pour compteur intelligent)
# =========================================================
try:
    from tensorflow.keras.models import Sequential
    from tensorflow.keras.layers import LSTM, Dense, Dropout
    TENSORFLOW_AVAILABLE = True
except ImportError:
    TENSORFLOW_AVAILABLE = False

def predict_lstm(series, steps=7, lookback=14):
    """Prédiction avec LSTM pour données quotidiennes (90+ jours)"""
    if not TENSORFLOW_AVAILABLE or len(series) < 90:
        return None # fallback vers ARIMA/SARIMA
    
    # Préparer les données
    data = series.values.reshape(-1, 1)
    X, y = [], []
    for i in range(lookback, len(data) - steps + 1):
        X.append(data[i-lookback:i, 0])
        y.append(data[i:i+steps, 0])
    X = np.array(X).reshape(-1, lookback, 1)
    y = np.array(y)
    
    if len(X) == 0:
        return None
    
    # Construire le modèle LSTM
    model = Sequential([
        LSTM(50, activation='relu', return_sequences=True, input_shape=(lookback, 1)),
        Dropout(0.2),
        LSTM(50, activation='relu'),
        Dropout(0.2),
        Dense(1)
    ])
    model.compile(optimizer='adam', loss='mse')
    model.fit(X, y, epochs=30, batch_size=8, verbose=0)
    
    # Prédiction itérative
    last_seq = data[-lookback:].reshape(1, lookback, 1)
    predictions = []
    for _ in range(steps):
        pred = model.predict(last_seq, verbose=0)[0, 0]
        predictions.append(pred)
        last_seq = np.append(last_seq[0, 1:, 0], pred).reshape(1, lookback, 1)
    return np.array(predictions)
# =========================================================
# WEATHER
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
st.image("Logo.jpg", width=150)
st.title("Power Risk-Gestion des risques électriques")

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
    menu_auth = st.radio("Choisissez :", ["Se connecter", "Créer un compte"])

    if menu_auth == "Se connecter":
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

    elif menu_auth == "Créer un compte":
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
    # Sidebar
    st.sidebar.image("Logo.jpg", width=120)
    st.sidebar.markdown("## ⚡ Power Risk")
    st.sidebar.markdown("Plateforme d'analyse avancée")
    
    # Vérifier si l'utilisateur est admin
    admin_mode = is_admin_user(st.session_state.user_id)
    
    if admin_mode:
        menu_options = ["Accueil", "Données", "Analyse", "Prévision", "Rapport", "Solutions", "Admin"]
    else:
        menu_options = ["Accueil", "Données", "Analyse", "Prévision", "Rapport", "Solutions"]
    
    menu = st.sidebar.radio("Navigation", menu_options)
    
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

# ========== PAGE ACCUEIL ==========
# ========== PAGE ACCUEIL ==========
if menu == "Accueil":
    st.title("⚡ PowerRisk")
    st.subheader("Plateforme de gestion et d'analyse des données électriques")

    st.markdown("""
    ## 📌 Bienvenue sur PowerRisk

    Cette plateforme vous aide à **centraliser**, **visualiser** et **analyser** vos données électriques.

    ---
    ## 📁 1. Comment entrer vos données ?

    | Méthode | Description | Périodicité / Quantité |
    |---------|-------------|------------------------|
    | 🟢 **Mode Simulation** | Génère des données aléatoires pour tester. | 50 valeurs |
    | 🟡 **Facture PDF (BT)** | Téléchargez une facture Sonelgaz (PDF). | 1 valeur |
    | 🔵 **Fichier CSV (MT)** | Importez un fichier CSV (compteurs intelligents). | Selon fichier |
    | 🔌 **Compteur intelligent (API)** | Connexion automatique via API. | Données quotidiennes |
    | 📡 **Arduino + Capteur** | Récupérez les données depuis Arduino. | Selon fréquence |

    ---
    ## 🧭 2. Que trouverez-vous dans chaque page ?

    | Page | Fonctionnalités | Coût en points |
    |------|----------------|----------------|
    | **📁 Données** | Saisie ou import des données. | 0 point |
    | **📊 Analyse** | Calcul du taux de panne λ, test de normalité, probabilité de surcharge. | 0 point |
    | **🔮 Prévision** | Prévision de consommation et risque de coupure. | **5 points** |
    | **📄 Rapport** | Génération d’un rapport technique PDF. | **5 points** |
    | **🛠️ Solutions** | Simulation économique, optimisation horaire, chatbot IA. | **5 points** |

    > 💡 **Nouveau compte :** 20 points offerts.

    ---
    ## 💰 3. Acheter des points ou un abonnement

    """)

    # Affichage des offres en colonnes
    col1, col2, col3 = st.columns(3)

    with col1:
        st.markdown("#### 📦 Pack de 20 points")
        st.write("500 DZD")
        st.caption("+20 points (4 utilisations)")
        if st.button("Acheter 20 points", key="buy_points"):
            try:
                from bson.objectid import ObjectId
                points_col.update_one(
                    {"user_id": ObjectId(st.session_state.user_id)},
                    {"$inc": {"total_points": 20}}
                )
                st.success("✅ 20 points ajoutés avec succès !")
                st.rerun()
            except Exception as e:
                st.error(f"Erreur : {e}")

    with col2:
        st.markdown("#### 📅 Mensuel illimité")
        st.write("1 000 DZD / mois")
        st.caption("Accès illimité (Prévision, Rapport, Solutions)")
        if st.button("S'abonner mensuel", key="subscribe_monthly"):
            try:
                from datetime import datetime, timedelta
                from bson.objectid import ObjectId
                subscriptions_col.update_one(
                    {"user_id": ObjectId(st.session_state.user_id)},
                    {"$set": {"plan": "MONTHLY", "expiry_date": datetime.now() + timedelta(days=30)}}
                )
                st.success("✅ Abonnement mensuel activé pour 30 jours !")
                st.rerun()
            except Exception as e:
                st.error(f"Erreur : {e}")

    with col3:
        st.markdown("#### 📆 Annuel illimité")
        st.write("6 000 DZD / an")
        st.caption("Économie de 6 000 DZD par rapport au mensuel")
        if st.button("S'abonner annuel", key="subscribe_yearly"):
            try:
                from datetime import datetime, timedelta
                from bson.objectid import ObjectId
                subscriptions_col.update_one(
                    {"user_id": ObjectId(st.session_state.user_id)},
                    {"$set": {"plan": "YEARLY", "expiry_date": datetime.now() + timedelta(days=365)}}
                )
                st.success("✅ Abonnement annuel activé pour 365 jours !")
                st.rerun()
            except Exception as e:
                st.error(f"Erreur : {e}")

    # ========== NOUVEAU : SERVICE DE MAINTENANCE ÉLECTRIQUE ==========
    st.markdown("---")
    st.header("🔧 Service de maintenance électrique")
    st.markdown("""
    PowerRisk vous met en relation avec des **entreprises de maintenance électrique** proches de votre localisation.
    Que ce soit pour une intervention urgente, une vérification périodique ou une installation, nous vous aidons à trouver le bon partenaire.
    """)

    st.subheader("📋 Nos partenaires de maintenance (exemples)")
    
    # Liste fictive de sociétés de maintenance (à remplacer par de vrais partenaires plus tard)
    maintenance_companies = [
        {
            "nom": "ÉlecTech Algérie",
            "ville": "Alger",
            "telephone": "05** ** ** **",
            "site": "www.ele***.dz"
        },
        {
            "nom": "PowerCare Solutions",
            "ville": "Oran",
            "telephone": "05** ** ** **",
            "site": "www.powe***.dz"
        },
        {
            "nom": "Maintenance Plus",
            "ville": "Constantine",
            "telephone": "05** ** ** **",
            "site": "www.maint***.dz"
        },
        {
            "nom": "Sécurité Élec",
            "ville": "Sétif",
            "telephone": "05** ** ** **",
            "site": "www.secur***.dz"
        },
        {
            "nom": "Énergie Service",
            "ville": "Annaba",
            "telephone": "05** ** ** **",
            "site": "www.energ***.dz"
        }
    ]
    
    # Affichage sous forme d'expandeur
    for company in maintenance_companies:
        with st.expander(f"🏢 {company['nom']} - {company['ville']}"):
            st.write(f"📞 Téléphone : {company['telephone']}")
            st.write(f"🌐 Site web : {company['site']}")
    
    st.caption("⚠️ Ces sociétés sont présentées à titre d'exemple. Contactez-nous pour devenir partenaire.")

    # ========== CONTACTEZ-NOUS ==========
    st.markdown("---")
    st.header("📞 Contactez PowerRisk")
    st.markdown("""
    Vous avez une question, une suggestion ou vous souhaitez devenir partenaire ?  
    Notre équipe est à votre disposition.
    """)
    
    col_contact1, col_contact2 = st.columns(2)
    with col_contact1:
        st.subheader("📧 Email")
        st.markdown("**powerrisk22@gmail.com")
        st.caption("Réponse sous 24h ouvrées")
    with col_contact2:
        st.subheader("📞 Téléphone / WhatsApp")
        st.markdown("**+213 7XX XX XX XX**")
        st.caption("Du dimanche au jeudi, 9h - 17h")
    
    st.info("💡 Vous pouvez également utiliser le **chatbot** dans la page 'Solutions' pour une assistance instantanée.")

    # ========== FIN DES AJOUTS ==========

    st.success("✅ PowerRisk – Plateforme claire, intuitive et professionnelle.")
    st.info("💡 Besoin d’aide ? Utilisez le chatbot dans la page 'Solutions'.")

# ========== PAGE DONNÉES ==========
elif menu == "Données":
    st.title("📁 Gestion des Données Industrielles")
    st.subheader("🌤️ Conditions météo actuelles")
    if "lat" not in st.session_state:
        st.session_state.lat = None
        st.session_state.lon = None
        st.session_state.weather_loaded = False
    if st.button("📍 Détecter ma position"):
        try:
            location = streamlit_js_eval(js_expressions="navigator.geolocation.getCurrentPosition((pos) => { return pos.coords.latitude + ',' + pos.coords.longitude; })", key="gps_loc")
            if location and location != "None" and "," in location:
                st.session_state.lat, st.session_state.lon = map(float, location.split(","))
                st.success(f"📍 Localisation détectée: {st.session_state.lat:.4f}, {st.session_state.lon:.4f}")
            else:
                st.warning("⚠️ Impossible de détecter la position.")
        except:
            st.warning("⚠️ Erreur de géolocalisation.")
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
    if st.session_state.lat is not None and st.session_state.lon is not None:
        try:
            api_key = "fd6a9aa64777078b3f7c711fb754b431"
            url_weather = f"http://api.openweathermap.org/data/2.5/weather?lat={st.session_state.lat}&lon={st.session_state.lon}&appid={api_key}&units=metric"
            res_weather = requests.get(url_weather).json()
            if res_weather.get("main"):
                st.session_state.temperature = res_weather["main"]["temp"]
                st.session_state.wind = res_weather["wind"]["speed"]
                st.session_state.weather_desc = res_weather["weather"][0]["description"]
                st.session_state.weather_loaded = True
            else:
                st.error("Erreur récupération météo")
        except Exception as e:
            st.error(f"Erreur: {e}")
    if st.session_state.get("weather_loaded", False):
        col_met1, col_met2, col_met3 = st.columns(3)
        col_met1.metric("🌡️ Température", f"{st.session_state.temperature:.1f} °C")
        col_met2.metric("💨 Vent", f"{st.session_state.wind:.1f} km/h")
        col_met3.metric("🌥️ Description", st.session_state.get("weather_desc", "N/A"))
    else:
        st.info("👆 Cliquez sur 'Détecter ma position' ou entrez une ville.")
    st.markdown("---")
    data_mode = st.radio("Choisissez le type de données", [
        "🟢 Mode Simulation",
        "🟡 BT - Factures (PDF)",
        "🔵 MT - Compteurs intelligents (CSV)",
        "🔌 Compteur intelligent (API)",
        "📡 Arduino + Capteur",
        "🔵 Compteur intelligent (données quotidiennes réalistes)"
    ])
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
                    st.success(f"Consommation: {conso} kWh, λ = {lambda_calculee:.6f}")
            else:
                st.error("Veuillez uploader un PDF.")
    elif data_mode == "📡 Arduino + Capteur":
        st.info("📡 Connectez votre Arduino ou téléchargez un fichier de données.")
        st.markdown("""
        **Options :**
         1. **Upload d’un fichier CSV** provenant de l’Arduino (avec colonnes : consommation, tension, courant).
         2. **Simulation** pour tester (génère des données similaires à un capteur).
        """)
        arduino_mode = st.radio("Mode de récupération", ["Simuler des données", "Uploader un fichier CSV"])
        if arduino_mode == "Simuler des données":
            if st.button("Générer données Arduino"):
                consommations = list(np.random.normal(250, 40, 50))
                voltage = float(np.random.normal(220, 8))
                current = float(np.random.normal(30, 12))
                nb_coupures_simulees = np.random.poisson(0.08, 1)[0]
                duree_heures = 50 * 24
                lambda_calculee = nb_coupures_simulees / duree_heures if duree_heures > 0 else 0.0001
                st.session_state.consommations = consommations
                st.session_state.voltage = voltage
                st.session_state.current = current
                st.session_state.lambda_panne = lambda_calculee
                st.success(f"✅ Données Arduino simulées : {len(consommations)} valeurs.")
        else:
            csv_file = st.file_uploader("Uploader fichier CSV (Arduino)", type=["csv"])
            if csv_file:
                df = pd.read_csv(csv_file)
                st.dataframe(df.head())
                col_energy = st.selectbox("Colonne consommation (kWh)", df.columns)
                col_voltage = st.selectbox("Colonne tension (V)", df.columns)
                col_current = st.selectbox("Colonne courant (A)", df.columns)
                if st.button("Analyser données Arduino"):
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
                    st.success(f"Données Arduino enregistrées. λ = {lambda_calculee:.6f}")
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
    elif data_mode == "🔵 Compteur intelligent (données quotidiennes réalistes)":
         st.info("📡 Simulation d’un compteur intelligent produisant des données quotidiennes avec tendance et saisonnalité.")
         jours = st.slider("Nombre de jours à générer", 30, 180, 90)
         if st.button("Générer données compteur intelligent"):
            # Générer des données réalistes pour LSTM
             dates = pd.date_range(end=datetime.today(), periods=jours, freq='D')
            
            # Tendance linéaire (augmentation lente)
             trend = np.linspace(200, 280, jours)
            # Saisonnalité hebdomadaire (cycle de 7 jours)
             weekly = 20 * np.sin(2 * np.pi * np.arange(jours) / 7)
            # Bruit réaliste
             noise = np.random.normal(0, 8, jours)
            # Consommation finale
             consommations = (trend + weekly + noise).tolist()
            
            # Tension et courant
             voltage = float(np.random.normal(220, 2))
             current = float(np.random.normal(30, 3))
            
            # Simuler des pannes (une par semaine environ)
             nb_pannes = max(1, int(jours / 7) + np.random.randint(-1, 2))
             dates_pannes = pd.date_range(end=datetime.today(), periods=nb_pannes, freq='7D')
             st.session_state["historique_pannes_sim"] = pd.DataFrame({
                 "date": dates_pannes,
                 "duree (min)": np.random.randint(15, 120, nb_pannes),
                 "cause": np.random.choice(["Surcharge", "Tempête", "Équipement"], nb_pannes)
            })
             lambda_calculee = nb_pannes / (jours * 24)
            
            # Sauvegarde
             st.session_state.consommations = consommations
             st.session_state.voltage = voltage
             st.session_state.current = current
             st.session_state.lambda_panne = lambda_calculee
            # Métadonnées pour LSTM
             st.session_state.data_source = "smart_meter_sim"
             st.session_state.data_freq = "D"
             st.session_state.is_random = False  
             st.success(f"✅ Données compteur intelligent générées ({jours} jours) avec {nb_pannes} pannes simulées.")
    elif data_mode == "🔌 Compteur intelligent (API)":
        st.info("📡 Connectez-vous à votre compteur intelligent via API.")
        api_url = st.text_input("URL de l'API (ex: https://api.compteur.com/v1/data)")
        api_key = st.text_input("Clé API (optionnelle)", type="password")
        if st.button("Récupérer les données"):
            if api_url:
                try:
                    st.warning("⚠️ Mode démonstration : génération de données simulées.")
                    consommations = list(np.random.normal(250, 30, 30))
                    voltage = float(np.random.normal(220, 5))
                    current = float(np.random.normal(30, 10))
                    nb_coupures_simulees = np.random.poisson(0.05, 1)[0]
                    duree_heures = 30 * 24
                    lambda_calculee = nb_coupures_simulees / duree_heures if duree_heures > 0 else 0.0001
                    st.session_state.consommations = consommations
                    st.session_state.voltage = voltage
                    st.session_state.current = current
                    st.session_state.lambda_panne = lambda_calculee
                    st.success(f"✅ Données récupérées via API (simulées) : {len(consommations)} valeurs.")
                except Exception as e:
                    st.error(f"Erreur lors de l'appel API : {e}")
            else:
                st.error("Veuillez entrer une URL API valide.")
    elif data_mode == "🔵 Compteur intelligent (données quotidiennes réalistes)":
        st.info("📡 Simulation d’un compteur intelligent produisant des données quotidiennes avec tendance et saisonnalité.")
        jours = st.slider("Nombre de jours à générer", 30, 180, 90)
        if st.button("Générer données compteur intelligent"):
            # Générer des données réalistes pour LSTM
            dates = pd.date_range(end=datetime.today(), periods=jours, freq='D')
            
            # Tendance linéaire (augmentation lente)
            trend = np.linspace(200, 280, jours)
            # Saisonnalité hebdomadaire (cycle de 7 jours)
            weekly = 20 * np.sin(2 * np.pi * np.arange(jours) / 7)
            # Bruit réaliste
            noise = np.random.normal(0, 8, jours)
            # Consommation finale
            consommations = (trend + weekly + noise).tolist()
            
            # Tension et courant
            voltage = float(np.random.normal(220, 2))
            current = float(np.random.normal(30, 3))
            
            # Simuler des pannes (une par semaine environ)
            nb_pannes = max(1, int(jours / 7) + np.random.randint(-1, 2))
            dates_pannes = pd.date_range(end=datetime.today(), periods=nb_pannes, freq='7D')
            st.session_state["historique_pannes_sim"] = pd.DataFrame({
                "date": dates_pannes,
                "duree (min)": np.random.randint(15, 120, nb_pannes),
                "cause": np.random.choice(["Surcharge", "Tempête", "Équipement"], nb_pannes)
            })
            lambda_calculee = nb_pannes / (jours * 24)
            
            # Sauvegarde
            st.session_state.consommations = consommations
            st.session_state.voltage = voltage
            st.session_state.current = current
            st.session_state.lambda_panne = lambda_calculee
            # Métadonnées pour LSTM
            st.session_state.data_source = "smart_meter_sim"
            st.session_state.data_freq = "D"
            st.session_state.is_random = False
            
            st.success(f"✅ Données compteur intelligent générées ({jours} jours) avec {nb_pannes} pannes simulées.")
            
    if st.session_state.consommations:
        st.subheader("📊 Aperçu des données actuelles")
        st.line_chart(st.session_state.consommations)
        col_a, col_b, col_c = st.columns(3)
        col_a.metric("⚡ Taux de panne λ", f"{st.session_state.lambda_panne:.6f} /heure")
        col_b.metric("🔌 Voltage moyen", f"{st.session_state.get('voltage', 0):.1f} V")
        col_c.metric("💡 Courant moyen", f"{st.session_state.get('current', 0):.1f} A")
        if st.session_state.get("weather_loaded", False):
            st.info(f"🌡️ Température actuelle: {st.session_state.temperature:.1f}°C | 💨 Vent: {st.session_state.wind:.1f} km/h")


# ========== PAGE ANALYSE ==========
elif menu == "Analyse":
    st.title("📊 Analyse des Risques")
    if "consommations" not in st.session_state or len(st.session_state["consommations"]) == 0:
        st.warning("⚠️ Aucune donnée de consommation. Veuillez d'abord charger des données dans la page 'Données'.")
        st.stop()
    
    consommations = st.session_state["consommations"]
    lambda_panne = st.session_state.get("lambda_panne", 0.0001)
    temp = st.session_state.get("temperature", 25.0)
    wind = st.session_state.get("wind", 10.0)
    if lambda_panne <= 0:
        lambda_panne = 0.0001
    
    st.subheader("📈 Résumé des données d'entrée")
    col1, col2, col3 = st.columns(3)
    col1.metric("📊 Nombre de mesures", len(consommations))
    col2.metric("⚡ Taux de panne λ", f"{lambda_panne:.6f} /h")
    col3.metric("🌡️ Température", f"{temp:.1f} °C")
    st.caption(f"💨 Vent : {wind:.1f} km/h")
    
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
    
    st.subheader("1️⃣ Probabilité de surcharge électrique")
    series = pd.Series(consommations)
    mean_val = series.mean()
    std_val = series.std() if series.std() != 0 else 1.0
    seuil = mean_val + 1.5 * std_val
    
    if normal_assumption:
        predicted_value = series.iloc[-1]
        P_A = 1 - norm.cdf(seuil, loc=predicted_value, scale=std_val)
        ic_low = mean_val - 1.96 * std_val / np.sqrt(len(series))
        ic_high = mean_val + 1.96 * std_val / np.sqrt(len(series))
        st.info(f"📊 **Intervalle de confiance 95% de la consommation moyenne** : [{ic_low:.1f}, {ic_high:.1f}] kWh")
    else:
        k = seuil / std_val if std_val > 0 else 1
        P_A = 1 / (k**2) if k > 1 else 1.0
        P_A = min(P_A, 1.0)
        st.info("⚠️ Utilisation de l'inégalité de Bienaymé-Tchebychev (sans hypothèse de normalité)")
    P_A = float(max(0, min(P_A, 1)))
    st.metric("⚡ Probabilité de dépassement du seuil", f"{P_A*100:.2f} %")
    st.caption(f"Seuil calculé : {seuil:.2f} kWh (moyenne + 1.5σ)")
    
    st.subheader("2️⃣ Probabilité de panne (fiabilité réseau)")
    P_B = 1 - np.exp(-lambda_panne)
    MTBF = 1 / lambda_panne
    st.metric("🔧 Probabilité de panne (dans l'heure)", f"{P_B*100:.2f} %")
    st.metric("⏱️ MTBF (Mean Time Between Failures)", f"{MTBF:.1f} heures")
    
    st.subheader("3️⃣ Impact météo (modèle logistique)")
    if "weather_model" not in st.session_state:
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
    
    st.subheader("4️⃣ Calcul du risque global (fusion personnalisable)")
    col_w1, col_w2, col_w3 = st.columns(3)
    with col_w1:
        w_A = st.slider("Poids surcharge", 0.0, 1.0, 0.4, 0.05)
    with col_w2:
        w_B = st.slider("Poids fiabilité", 0.0, 1.0, 0.3, 0.05)
    with col_w3:
        w_C = st.slider("Poids météo", 0.0, 1.0, 0.3, 0.05)
    total = w_A + w_B + w_C
    if total > 0:
        w_A, w_B, w_C = w_A/total, w_B/total, w_C/total
    
    Risk = w_A * P_A + w_B * P_B + w_C * P_C
    Risk = float(max(0, min(Risk, 1)))
    st.metric("🎯 **Indice de Risque Global**", f"{Risk*100:.2f} %")
    
    if Risk < 0.4:
        st.success("🟢 **Niveau Faible** – Aucune action immédiate requise")
    elif Risk < 0.7:
        st.warning("🟠 **Niveau Moyen** – Surveillance renforcée recommandée")
    else:
        st.error("🔴 **Niveau Élevé** – Intervention nécessaire")
    
    fig, ax = plt.subplots()
    ax.bar(["Surcharge", "Fiabilité", "Météo"], [P_A, P_B, P_C], color=['#1f77b4', '#ff7f0e', '#2ca02c'])
    ax.set_ylabel("Probabilité")
    ax.set_title("Comparaison des facteurs de risque")
    ax.set_ylim(0, 1)
    for i, v in enumerate([P_A, P_B, P_C]):
        ax.text(i, v + 0.02, f"{v*100:.1f}%", ha='center')
    st.pyplot(fig)
    
    st.session_state["risk_final"] = Risk * 100
    st.session_state["P_A"] = P_A
    st.session_state["P_B"] = P_B
    st.session_state["P_C"] = P_C
    st.session_state["lambda_used"] = lambda_panne
    
    with st.expander("📐 Voir les détails mathématiques"):
        st.markdown(r"""
        **1. Probabilité de surcharge**  
        - Hypothèse normale : $P_A = 1 - \Phi\left(\frac{S - \hat{x}_{t+1}}{\sigma}\right)$  
        - Sinon : Inégalité de Bienaymé-Tchebychev $P(|X-\mu|\ge k\sigma) \le \frac{1}{k^2}$.
        **2. Probabilité de panne (fiabilité)**  
        - Loi exponentielle : $P_B = 1 - e^{-\lambda t}$ avec $t=1$ heure.
        **3. Impact météo**  
        - Régression logistique : $P_C = \frac{1}{1+e^{-(\beta_0 + \beta_1 T + \beta_2 V)}}$.
        **4. Risque global**  
        - $R = w_A P_A + w_B P_B + w_C P_C$, avec $w_i$ personnalisables.
        """)

# ========== PAGE PRÉVISION ==========
elif menu == "Prévision":
    st.title("⚡ Prévision intelligente de la consommation et des coupures")

    # ---------- Vérification admin / points ----------
    if not is_admin_user(st.session_state.user_id):
        access, detail = can_access_page(st.session_state.user_id)
        if not access:
            st.error(f"❌ Vous n'avez pas assez de points. Solde : {detail} points. (5 points requis)")
            st.info("💡 Achetez un pack de points ou abonnez-vous.")
            st.stop()
        if detail == "points":
            use_points(st.session_state.user_id)
            st.info("ℹ️ 5 points déduits pour cette consultation.")

    # ---------- Récupération des données ----------
    consommations = st.session_state.get("consommations", [])
    data_source = st.session_state.get("data_source", "inconnu")
    data_freq = st.session_state.get("data_freq", "D")
    is_random = st.session_state.get("is_random", False)
    lambda_panne = st.session_state.get("lambda_panne", 0.0001)
    temperature = st.session_state.get("temperature", 20.0)
    vent = st.session_state.get("wind", 10.0)

    if len(consommations) < 5:
        st.warning("⚠️ Pas assez de données (minimum 5 valeurs). Utilisez la page 'Données'.")
        st.stop()

    n = len(consommations)

    # ---------- Informations ----------
    st.subheader("📌 Informations sur vos données")
    col_info1, col_info2 = st.columns(2)
    with col_info1:
        st.write(f"**Source :** {data_source.replace('_', ' ').title()}")
        st.write(f"**Nombre de valeurs :** {n}")
    with col_info2:
        st.write(f"**Fréquence :** {data_freq}")
        st.write(f"**Aléatoire :** {'Oui' if is_random else 'Non'}")

    # ---------- Choix du modèle ----------
    use_lstm = False
    if data_source == "smart_meter_sim" and data_freq == "D" and n >= 90:
        st.info("🤖 Données quotidiennes longues (≥ 90 jours). Utilisation du modèle **LSTM**.")
        use_lstm = True
        periodes = st.slider("Nombre de jours à prévoir", 1, 30, 7)
        lookback = st.slider("Fenêtre d'historique (jours)", 7, 30, 14)
    else:
        st.info("📈 Utilisation du modèle **ARIMA** (prévision simple).")
        periodes = st.slider("Nombre de périodes à prévoir", 1, 14, 7)

    # ---------- Préparation DataFrame ----------
    dates = pd.date_range(end=datetime.today(), periods=n, freq='D')
    df = pd.DataFrame({"date": dates, "consommation": consommations})
    df.set_index("date", inplace=True)

    # ---------- Exécution ----------
    st.subheader("🔮 Prévision de la consommation")
    try:
        if use_lstm:
            forecast = predict_lstm(pd.Series(consommations), steps=periodes, lookback=lookback)
            if forecast is None:
                st.warning("⚠️ LSTM non disponible (TensorFlow manquant). Utilisation d'ARIMA.")
                use_lstm = False
        if not use_lstm:
            forecast = predict_arima(pd.Series(consommations), steps=periodes)

        future_dates = pd.date_range(start=df.index[-1] + timedelta(days=1), periods=periodes, freq='D')
        df_prev = pd.DataFrame({
            "Date": future_dates.strftime("%d/%m/%Y"),
            "Consommation prévue (kWh)": np.round(forecast, 1)
        })
        st.table(df_prev)

        fig, ax = plt.subplots()
        ax.plot(df.index, df["consommation"], label="Historique", color='blue')
        ax.plot(future_dates, forecast, label="Prévision", color='red', marker='o')
        ax.set_title("Évolution de la consommation")
        ax.legend()
        st.pyplot(fig)

        variation = (forecast[-1] - df["consommation"].iloc[-1]) / df["consommation"].iloc[-1] * 100
        if variation > 10:
            st.warning(f"⚠️ Augmentation de {variation:.1f}% attendue.")
        elif variation < -10:
            st.success(f"✅ Baisse de {abs(variation):.1f}% attendue.")
        else:
            st.info(f"📉 Variation stable ({variation:.1f}%).")
    except Exception as e:
        st.error(f"Erreur : {e}")
        st.stop()

    # ---------- Risque de coupure (identique) ----------
    st.subheader("⚠️ Risque de coupure électrique dans les prochaines 24h")
    if "historique_pannes_sim" in st.session_state:
        df_pannes = st.session_state["historique_pannes_sim"]
    else:
        dates_pannes = pd.date_range(start=datetime.today() - timedelta(days=60), periods=8, freq='7D')
        df_pannes = pd.DataFrame({
            "date": dates_pannes,
            "duree (min)": np.random.randint(10, 180, 8),
            "cause": np.random.choice(["Surcharge", "Tempête", "Équipement", "Foudre"], 8)
        })
    with st.expander("📋 Historique des dernières coupures"):
        st.dataframe(df_pannes.tail(5))

    conso_actuelle = consommations[-1]
    seuil_charge = np.mean(consommations) * 1.2
    charge_elevee = conso_actuelle > seuil_charge
    conditions_meteo_risque = (temperature > 35) or (vent > 45)
    pannes_recentes = df_pannes[df_pannes["date"] > datetime.today() - timedelta(days=30)]
    proba_hist = len(pannes_recentes) / 30 if len(pannes_recentes) > 0 else 0.03

    if charge_elevee and conditions_meteo_risque:
        proba_risque = min(proba_hist * 4, 0.95)
        message = "🔴 Risque très élevé"
    elif charge_elevee or conditions_meteo_risque:
        proba_risque = min(proba_hist * 2, 0.70)
        message = "🟠 Risque modéré"
    else:
        proba_risque = proba_hist * 0.8
        message = "🟢 Risque faible"

    proba_lambda = 1 - np.exp(-lambda_panne * 24)
    proba_finale = 0.6 * proba_risque + 0.4 * proba_lambda
    proba_finale = min(proba_finale, 0.99)
    st.metric("📊 Probabilité de coupure dans les 24h", f"{proba_finale*100:.1f}%")
    st.info(message)

    st.subheader("💡 Que faire maintenant ?")
    if proba_finale > 0.6:
        st.error("**Actions recommandées :**\n- Réduisez immédiatement l'usage des appareils puissants.\n- Préparez un groupe électrogène.\n- Contactez votre fournisseur.")
    elif proba_finale > 0.3:
        st.warning("**Précautions :**\n- Surveillez votre consommation chaque heure.\n- Évitez de lancer plusieurs gros appareils en même temps.")
    else:
        st.success("**Situation stable :** vous pouvez travailler normalement.")

# ========== PAGE RAPPORT ==========
elif menu == "Rapport":
    st.title("📄 Rapport Intelligent - Analyse des Risques")
    
    if not is_admin_user(st.session_state.user_id):
        access, detail = can_access_page(st.session_state.user_id)
        if not access:
            st.error(f"❌ Points insuffisants. Solde : {detail} points. (5 points requis)")
            st.stop()
        if detail == "points":
            use_points(st.session_state.user_id)
            st.info("ℹ️ 5 points déduits pour ce rapport.")
    
    if "risk_final" not in st.session_state:
        st.warning("⚠️ Veuillez d'abord effectuer l'analyse du risque dans la page 'Analyse'.")
        st.stop()
    risk_percent = float(st.session_state.get("risk_final", 50.0))
    P_A = float(st.session_state.get("P_A", 0.2))
    P_B = float(st.session_state.get("P_B", 0.2))
    P_C = float(st.session_state.get("P_C", 0.2))
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
    st.subheader("📌 1. Résumé exécutif")
    resume = f"Le niveau global de risque du réseau électrique est estimé à **{risk_percent:.1f}%**, ce qui correspond à un niveau **{niveau}**. Cette évaluation combine : - Probabilité de surcharge (P_A = {P_A*100:.1f}%) - Probabilité de panne (P_B = {P_B*100:.1f}%) - Impact météo (P_C = {P_C*100:.1f}%)"
    st.info(resume)
    st.subheader("⚠️ 2. Degré de criticité du réseau")
    if couleur == "success":
        st.success(zone)
    elif couleur == "warning":
        st.warning(zone)
    else:
        st.error(zone)
    st.subheader("🔧 3. Impact technique sur les équipements")
    impact_text = "- **Transformateurs** : Risque d'échauffement thermique accru.\n- **Lignes électriques** : Dilatation des conducteurs.\n- **Protections** : Possibilité de déclenchement intempestif.\n- **Continuité de service** : Probabilité d'interruption augmentée."
    st.write(impact_text)
    st.subheader("📊 4. Analyse des facteurs de risque")
    facteurs = {"Surcharge": P_A, "Fiabilité": P_B, "Météo": P_C}
    dominant = max(facteurs, key=facteurs.get)
    st.write(f"**Facteur dominant** : **{dominant}** (probabilité = {facteurs[dominant]*100:.1f}%)")
    fig, ax = plt.subplots()
    ax.bar(["Surcharge", "Fiabilité", "Météo"], [P_A, P_B, P_C], color=['#1f77b4', '#ff7f0e', '#2ca02c'])
    ax.set_ylabel("Probabilité")
    ax.set_title("Comparaison des facteurs de risque")
    ax.set_ylim(0, 1)
    for i, v in enumerate([P_A, P_B, P_C]):
        ax.text(i, v + 0.02, f"{v*100:.1f}%", ha='center')
    st.pyplot(fig)
    st.subheader("🔮 5. Scénarios prospectifs")
    st.write(f"- **Scénario 1 – Maintien tendance actuelle** : risque autour de {risk_percent:.1f}%.\n- **Scénario 2 – Maintenance préventive** : réduction du risque.\n- **Scénario 3 – Capacités solaires/batteries** : baisse du risque de surcharge.")
    st.subheader("🛠️ 6. Décision d'ingénierie recommandée")
    if dominant == "Surcharge":
        decision_text = "Intervention ciblée sur la surcharge : installer une solution de peak shaving (solaire + batteries), renforcer la capacité du transformateur."
    elif dominant == "Fiabilité":
        decision_text = "Intervention ciblée sur la fiabilité : maintenance préventive systématique, installation de redondance (UPS, groupes électrogènes)."
    else:
        decision_text = "Intervention ciblée sur le climat : améliorer la ventilation des locaux techniques, surveiller les prévisions météo."
    st.write(decision_text)
    st.subheader("📑 7. Exporter le rapport")
    if st.button("Générer le rapport technique (PDF)"):
        try:
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
                st.download_button(label="Télécharger le rapport (PDF)", data=f, file_name="PowerRisk_Rapport.pdf", mime="application/pdf")
            os.unlink(pdf_file.name)
        except Exception as e:
            st.error(f"Erreur lors de la génération du PDF : {e}")
# ========== PAGE SOLUTIONS ==========
elif menu == "Solutions":
    st.title("🛠 Solutions Recommandées - Analyse & Décision")
    
    if not is_admin_user(st.session_state.user_id):
        access, detail = can_access_page(st.session_state.user_id)
        if not access:
            st.error(f"❌ Points insuffisants. Solde : {detail} points. (5 points requis)")
            st.stop()
        if detail == "points":
            use_points(st.session_state.user_id)
            st.info("ℹ️ 5 points déduits pour accéder aux solutions.")
    
    def calcul_van_roi(investissement, flux_annuel, taux, annees):
        if investissement <= 0:
            return 0.0, 0.0
        van = -investissement
        for t in range(1, annees + 1):
            van += flux_annuel / ((1 + taux) ** t)
        roi = investissement / flux_annuel if flux_annuel > 0 else float('inf')
        return van, roi
    
    if "risk_final" not in st.session_state:
        st.warning("⚠️ Veuillez d'abord effectuer l'analyse du risque (page 'Analyse').")
        st.stop()
    
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
        
        st.header("💰 2. Simulation économique : comparaison des solutions")
        with st.expander("🔧 Paramètres économiques"):
            prix_kwh = st.number_input("💵 Prix du kWh (DZD)", 5, 30, 8)
            taux_actualisation = st.slider("📉 Taux d'actualisation (%)", 0, 15, 8) / 100.0
            duree_projet = st.slider("📅 Durée du projet (années)", 5, 25, 15)
        
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
        
        with st.expander("🔋 Solution 2 : Batterie de stockage"):
            cout_batterie_par_kwh = st.number_input("💰 Coût batterie (DZD/kWh utile)", 30000, 150000, 70000)
            duree_vie_batterie = st.slider("🔋 Durée de vie batterie (ans)", 5, 15, 10)
            depth_discharge = st.slider("Profondeur de décharge utile (%)", 50, 95, 80) / 100.0
            capacite_utile_kwh = target_energy_kwh / depth_discharge
            invest_batterie = capacite_utile_kwh * cout_batterie_par_kwh
            econ_annuelle_batterie = target_energy_kwh * prix_kwh * 365
            VAN_batterie, ROI_batterie = calcul_van_roi(invest_batterie, econ_annuelle_batterie, taux_actualisation, min(duree_projet, duree_vie_batterie))
        
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
        
        st.header("⏰ 3. Optimisation temporelle (Time-of-Use)")
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
        
        st.header("🤖 4. Assistant IA - Posez vos questions")
        GEMINI_API_KEY = "AIzaSyA6OEjzOfg5LxOS4Nb9XWF174SZvvOGTTk" # Remplacez par votre clé
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
                try:
                    genai.configure(api_key=GEMINI_API_KEY)
                    model = genai.GenerativeModel('gemini-1.5-flash')
                    api_ok = True
                except Exception as e:
                    st.error(f"❌ Erreur API Gemini: {e}")
                    api_ok = False
                if api_ok:
                    for msg in st.session_state.messages:
                        with st.chat_message(msg["role"]):
                            st.markdown(msg["content"])
                    user_input = st.chat_input("Posez une question sur les résultats ou les solutions...")
                    if user_input:
                        st.session_state.messages.append({"role": "user", "content": user_input})
                        with st.chat_message("user"):
                            st.markdown(user_input)
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
                    if st.button("🗑️ Effacer la conversation"):
                        st.session_state.messages = []
                        st.rerun()
    
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
# ========== PAGE ADMIN ==========

# ========== PAGE ADMIN ==========
elif menu == "Admin" and is_admin_user(st.session_state.user_id):
    st.title("👑 Administration - PowerRisk")
    st.markdown("Bienvenue, administrateur. Vous avez un accès illimité à toutes les fonctionnalités.")
    
    tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs([
        "📊 Dashboard", "👥 Utilisateurs", "⚠️ Risques", "🤖 IA", "💰 Abonnements", "📢 Notifications"
    ])
    
    # ---------- TAB 1 : DASHBOARD ----------
    with tab1:
        st.subheader("📊 Statistiques générales")
        total_users = users_col.count_documents({})
        total_admins = users_col.count_documents({"is_admin": 1})
        total_premium = subscriptions_col.count_documents({"plan": {"$in": ["MONTHLY", "YEARLY"]}})
        total_points_used = sum(p.get("used_points", 0) for p in points_col.find())
        total_analyses = len(list(entreprises_col.find()))
        
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("👥 Utilisateurs", total_users)
        col2.metric("👑 Admins", total_admins)
        col3.metric("⭐ Premium", total_premium)
        col4.metric("📊 Analyses effectuées", total_analyses)
        st.metric("🎯 Points consommés (total)", total_points_used)
        
        st.subheader("📈 Évolution des inscriptions (simulation)")
        # توليد تواريخ آخر 6 أشهر (أول يوم من كل شهر) - طريقة مستقلة عن pandas
        from datetime import datetime, timedelta
        today = datetime.today()
        dates = []
        for i in range(5, -1, -1):
            year = today.year
            month = today.month - i
            if month <= 0:
                month += 12
                year -= 1
            dates.append(datetime(year, month, 1))
        # محاكاة عدد المستخدمين الجدد
        users_per_month = np.random.randint(5, 30, size=6)
        fig, ax = plt.subplots()
        ax.plot(dates, users_per_month, marker='o', linestyle='-')
        ax.set_title("Nouveaux utilisateurs par mois")
        ax.set_xlabel("Mois")
        ax.set_ylabel("Nombre d'inscriptions")
        plt.xticks(rotation=45)
        st.pyplot(fig)
    
    # ---------- TAB 2 : GESTION DES UTILISATEURS ----------
    with tab2:
        st.subheader("👥 Gestion des utilisateurs")
        users = list(users_col.find())
        for user in users:
            with st.expander(f"📧 {user['email']} - {user.get('nom_complet', 'Nom inconnu')}"):
                col_a, col_b, col_c = st.columns([2, 1, 1])
                with col_a:
                    st.write(f"**ID:** {user['_id']}")
                    st.write(f"**Admin:** {'✅ Oui' if user.get('is_admin') else '❌ Non'}")
                    st.write(f"**Vérifié:** {'✅' if user.get('is_verified') else '❌'}")
                    pts = points_col.find_one({"user_id": user['_id']})
                    if pts:
                        st.write(f"**Points restants:** {pts['total_points'] - pts.get('used_points', 0)}")
                with col_b:
                    if not user.get('is_admin'):
                        if st.button("⭐ Promouvoir admin", key=f"promote_{user['_id']}"):
                            users_col.update_one({"_id": user['_id']}, {"$set": {"is_admin": 1}})
                            st.success(f"{user['email']} est maintenant admin")
                            st.rerun()
                    else:
                        if st.button("⬇️ Rétrograder", key=f"demote_{user['_id']}"):
                            users_col.update_one({"_id": user['_id']}, {"$set": {"is_admin": 0}})
                            st.success(f"{user['email']} n'est plus admin")
                            st.rerun()
                with col_c:
                    if st.button("🗑️ Supprimer", key=f"delete_{user['_id']}"):
                        users_col.delete_one({"_id": user['_id']})
                        entreprises_col.delete_many({"user_id": user['_id']})
                        points_col.delete_many({"user_id": user['_id']})
                        subscriptions_col.delete_many({"user_id": user['_id']})
                        st.success(f"Utilisateur {user['email']} supprimé")
                        st.rerun()
    
    # ---------- TAB 3 : SURVEILLANCE DES RISQUES ----------
    with tab3:
        st.subheader("⚠️ Surveillance des risques")
        st.info("Les utilisateurs avec un risque élevé seront listés ici (simulation).")
        data_risque = {
            "Utilisateur": ["client1@mail.com", "client2@mail.com", "client3@mail.com"],
            "Risque (%)": [85, 72, 45],
            "Dernière analyse": ["2025-04-10", "2025-04-09", "2025-04-08"]
        }
        df_risque = pd.DataFrame(data_risque)
        st.dataframe(df_risque)
        if st.button("📧 Envoyer une alerte aux utilisateurs à risque"):
            st.success("Alerte envoyée (simulation)")
    
    # ---------- TAB 4 : CONTRÔLE IA ----------
    with tab4:
        st.subheader("🤖 Contrôle des modèles IA")
        st.info("Paramètres des modèles de prévision et d'analyse.")
        st.write("**Modèle ARIMA:** ordre (1,1,1)")
        new_order = st.text_input("Nouvel ordre ARIMA (p,d,q)", "1,1,1")
        if st.button("Appliquer nouvel ordre"):
            st.success(f"Ordre ARIMA mis à jour : {new_order} (simulation)")
        st.write("**Modèle météo (Logistic Regression):** entraîné sur données simulées")
        if st.button("Ré-entraîner le modèle météo"):
            X_train = np.array([[25,10],[30,20],[35,30],[40,40],[45,60],[42,70]])
            y_train = np.array([0,0,1,1,1,1])
            model_weather = LogisticRegression()
            model_weather.fit(X_train, y_train)
            st.session_state["weather_model"] = model_weather
            st.success("Modèle météo ré-entraîné")
    
    # ---------- TAB 5 : ABONNEMENTS ----------
    with tab5:
        st.subheader("💰 Abonnements")
        total_subscriptions = subscriptions_col.count_documents({})
        st.write(f"Nombre total d'abonnements : {total_subscriptions}")
        plans = subscriptions_col.aggregate([
            {"$group": {"_id": "$plan", "count": {"$sum": 1}}}
        ])
        st.write("**Répartition des plans :**")
        for p in plans:
            st.write(f"- {p['_id']} : {p['count']} utilisateurs")
        st.subheader("Modifier les tarifs")
        new_monthly = st.number_input("Prix mensuel (DZD)", value=1000, step=100)
        new_yearly = st.number_input("Prix annuel (DZD)", value=6000, step=500)
        if st.button("Enregistrer nouveaux tarifs"):
            st.success(f"Nouveaux tarifs : {new_monthly} DZD/mois, {new_yearly} DZD/an (simulation)")
    
    # ---------- TAB 6 : NOTIFICATIONS ----------
    with tab6:
        st.subheader("📢 Envoi de notifications")
        notification_msg = st.text_area("Message à envoyer à tous les utilisateurs")
        if st.button("Envoyer la notification"):
            if notification_msg:
                st.success("Notification envoyée à tous les utilisateurs (simulation)")
            else:
                st.warning("Veuillez entrer un message")
