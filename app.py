import streamlit as st
import pandas as pd
import folium
from streamlit_folium import st_folium
from streamlit_js_eval import get_geolocation
from ortools.constraint_solver import routing_enums_pb2, pywrapcp
from math import radians, cos, sin, asin, sqrt
import requests
from streamlit_autorefresh import st_autorefresh

# 1. SEGURANÇA E MEMÓRIA DE ESTADO
MOTORISTAS_AUTORIZADOS = {"11972295576": "senha123", "ADMIN": "master00"}

if 'logado' not in st.session_state: st.session_state['logado'] = False
if 'df_otimizado' not in st.session_state: st.session_state['df_otimizado'] = None
if 'entregas_feitas' not in st.session_state: st.session_state['entregas_feitas'] = set()

def obter_rota_ruas(coords_list):
    try:
        locs = ";".join([f"{lon},{lat}" for lat, lon in coords_list])
        url = f"http://router.project-osrm.org/route/v1/driving/{locs}?overview=full&geometries=geojson"
        r = requests.get(url, timeout=15)
        if r.status_code == 200:
            return [[p[1], p[0]] for p in r.json()['routes'][0]['geometry']['coordinates']]
    except: pass
    return coords_list

# Interface de Login (Simplificada)
if not st.session_state['logado']:
    st.caption("Acesso Restrito")
    with st.form("login"):
        t = st.text_input("Usuário")
        s = st.text_input("Senha", type="password")
        if st.form_submit_button("Entrar"):
            if t in MOTORISTAS_AUTORIZADOS and MOTORISTAS_AUTORIZADOS[t] == s:
                st.session_state['logado'] = True
                st.rerun()
    st.stop()

st.set_page_config(page_title="Rota Pro", layout="wide")

# 2. CABEÇALHO COMPACTO
if st.session_state['df_otimizado'] is not None:
    st.caption("📍 ROTA ATIVA")
    st_autorefresh(interval=30000, key="datarefresh")
else:
    st.subheader("🚚 Otimizador de Rota")

loc = get_geolocation()
if loc and 'coords' in loc:
    lat_origem, lon_origem = loc['coords']['latitude'], loc['coords']['longitude']
else:
    st.warning("Aguardando GPS...")
    st.stop()

# 3. PROCESSAMENTO (AGRUPADO)
if st.session_state['df_otimizado'] is None:
    arquivo = st.file_uploader("Subir planilha", type=['csv', 'xlsx'])
    if arquivo and st.button("CALCULAR"):
        df_raw = pd.read_csv(arquivo) if arquivo.name.endswith('.csv') else pd.read_excel(arquivo)
        df = df_raw.groupby(['Latitude', 'Longitude'], as_index=False).agg({
            'Destination Address': 'first', 'Bairro': 'first', 'City': 'first', 'Stop': 'count'
        })
        # Lógica de cálculo simplificada aqui (mantendo a do post anterior)
        coords = [[lat_origem, lon_origem]] + df[['Latitude', 'Longitude']].values.tolist()
        manager = pywrapcp.RoutingIndexManager(len(coords), 1, 0)
        routing = pywrapcp.RoutingModel(manager)
        def dist_call(f, t):
            p1 = coords[manager.IndexToNode(f)]; p2 = coords[manager.IndexToNode(t)]
            la1, lo1 = map(radians, p1); la2, lo2 = map(radians, p2)
            return int(2 * asin(sqrt(sin((la2-la1)/2)**2 + cos(la1) * cos(la2) * sin((lo2-lo1)/2)**2)) * 6371000)
        transit_idx = routing.RegisterTransitCallback(dist_call)
        routing.SetArcCostEvaluatorOfAllVehicles(transit_idx)
        sol = routing.SolveWithParameters(pywrapcp.DefaultRoutingSearchParameters())
        if sol:
            idx, ordem = routing.Start(0), []
            while not routing.IsEnd(idx):
                ordem.append(manager.IndexToNode(idx))
                idx = sol.Value(routing.NextVar(idx))
            st.session_state['df_otimizado'] = df.iloc[[i-1 for i in ordem if i > 0]].copy()
            st.rerun()

# 4. MAPA E CARDS
if st.session_state['df_otimizado'] is not None:
    df_res = st.session_state['df_otimizado']
    
    # Mapa Giratório com Linha Fina
    m = folium.Map(location=[lat_origem, lon_origem], zoom_start=16, control_scale=True)
    
    # Rota: Cinza Escuro e Fina (weight=3)
    pontos_rota = [[lat_origem, lon_origem]] + df_res[['Latitude', 'Longitude']].values.tolist()
    folium.PolyLine(obter_rota_ruas(pontos_rota), color="#444444", weight=3, opacity=0.6).add_to(m)
    
    # Marcador do Motorista
    folium.CircleMarker([lat_origem, lon_origem], radius=4, color='red', fill=True).add_to(m)
    
    for i, row in enumerate(df_res.itertuples()):
        # Cor do balão: Preto para pendente, Verde para feito
        cor = "#28a745" if i in st.session_state['entregas_feitas'] else "#212529"
        
        icone = folium.DivIcon(html=f"""<div style="background-color:{cor}; color:white; border-radius:4px; width:20px; height:20px; 
            display:flex; align-items:center; justify-content:center; font-weight:bold; font-size:10px; border:1px solid white;">{i+1}</div>""")
        
        folium.Marker([row.Latitude, row.Longitude], icon=icone, 
                      popup=folium.Popup(f"{row._3}", max_width=200)).add_to(m)
    
    # Exibição do mapa
    st_folium(m, width="100%", height=380, key="mapa_v13")

    # 5. CARDS COMPACTOS (LADO A LADO)
    proxima = next(((i+1, r) for i, r in enumerate(df_res.itertuples()) if i not in st.session_state['entregas_feitas']), None)
    
    if proxima:
        idx, dados = proxima
        
        # Grid de Cards Pequenos
        c1, c2 = st.columns(2)
        with c1:
            st.metric("📦 Parada", f"#{idx}")
        with c2:
            st.metric("🔢 Volumes", f"{dados.Stop} un")
        
        # Card de Endereço Simplificado
        with st.expander("🏠 Ver Endereço Completo", expanded=True):
            st.write(f"**{dados._3}**")
            st.caption(f"{dados.Bairro} - {dados.City}")
        
        g_maps = f"https://www.google.com/maps/dir/?api=1&origin={lat_origem},{lon_origem}&destination={dados.Latitude},{dados.Longitude}&travelmode=driving"
        st.link_button("🚀 NAVEGAR", g_maps, use_container_width=True)
        
        if st.button("Finalizar Rota Atual", type="secondary"):
            st.session_state['df_otimizado'] = None
            st.rerun()
