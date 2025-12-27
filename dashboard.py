import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import plotly.express as px
import kagglehub
from kagglehub import KaggleDatasetAdapter

# ==========================================
# 1. PAGE CONFIGURATION & STYLING
# ==========================================
st.set_page_config(
    page_title="Ultimate Team Selector",
    page_icon="⚽",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom CSS for "Dark Mode" Analytics feel
st.markdown("""
<style>
    .stApp { background-color: #0e1117; }
    .stSelectbox, .stMultiSelect { color: white; }
    div[data-testid="stMetricValue"] { color: #00CC96; font-family: 'Helvetica Neue', sans-serif; }
    h1, h2, h3 { color: white; font-family: 'Helvetica Neue', sans-serif; }
    /* Tabs styling */
    .stTabs [data-baseweb="tab-list"] { gap: 24px; }
    .stTabs [data-baseweb="tab"] { height: 50px; white-space: pre-wrap; background-color: #1c1f26; border-radius: 4px 4px 0px 0px; gap: 1px; padding-top: 10px; padding-bottom: 10px; }
    .stTabs [aria-selected="true"] { background-color: #00CC96; color: white; }
</style>
""", unsafe_allow_html=True)

# ==========================================
# 2. DATA ENGINE (KAGGLE INTEGRATION)
# ==========================================
@st.cache_data
def load_data():
    try:
        with st.spinner('Downloading latest data from Kaggle...'):
            # Load dataset directly using kagglehub
            df = kagglehub.load_dataset(
                KaggleDatasetAdapter.PANDAS,
                "jacksonjohannessen/fifa-and-irl-soccer-player-data",
                "fifa_fbref_merged.csv"
            )
    except Exception as e:
        st.error(f"Error loading data from Kaggle: {e}")
        return pd.DataFrame()

    # Filter for meaningful data (Sample Size > 900 mins)
    if 'Playing Time_Min' in df.columns:
        df = df[df['Playing Time_Min'] > 900].copy()

    # Fill NaNs in critical columns
    fill_cols = ['value_eur', 'wage_eur', 'overall', 'potential', 'pace', 'shooting', 'passing', 'dribbling', 'defending', 'physic']
    for c in fill_cols:
        if c in df.columns: df[c] = df[c].fillna(0)

    # Position Mapping
    def get_pos(s):
        if not isinstance(s, str): return 'Unknown'
        p = s.split(',')[0]
        if p == 'GK': return 'GK'
        if p in ['CB','LB','RB','LWB','RWB']: return 'DEF'
        if p in ['CDM','CM','CAM','RM','LM']: return 'MID'
        return 'FWD'
    
    if 'player_positions' in df.columns:
        df['Pos_Group'] = df['player_positions'].apply(get_pos)
    
    return df

def normalize(series):
    return (series - series.min()) / (series.max() - series.min())

def calculate_custom_score(df, priorities):
    """
    Dynamically calculates a 'Scout Score' based on user priorities.
    """
    df['Scout_Score'] = 0.0
    
    # 1. SCORING (Attacking Output)
    if 'Scoring Efficiency' in priorities:
        score = 0.5*normalize(df.get('Per 90 Minutes_npxG', 0)) + 0.3*normalize(df.get('shooting', 0)) + 0.2*normalize(df.get('Per 90 Minutes_Gls', 0))
        df['Scout_Score'] += score * 2.0 
        
    # 2. CREATIVITY (Playmaking)
    if 'Playmaking & Assists' in priorities:
        score = 0.4*normalize(df.get('SCA_SCA90', 0)) + 0.4*normalize(df.get('Per 90 Minutes_PrgP', 0)) + 0.2*normalize(df.get('passing', 0))
        df['Scout_Score'] += score * 2.0

    # 3. DEFENSE (Wall)
    if 'Defensive Solidity' in priorities:
        score = 0.4*normalize(df.get('Per 90 Minutes_Tkl+Int', 0)) + 0.3*normalize(df.get('defending', 0)) + 0.3*normalize(df.get('physic', 0))
        df['Scout_Score'] += score * 2.0

    # 4. POTENTIAL (Wonderkids)
    if 'Future Potential' in priorities:
        gap = df['potential'] - df['overall']
        score = 0.6*normalize(gap) + 0.4*(1 - normalize(df['age_fifa']))
        df['Scout_Score'] += score * 2.5 

    # 5. ROI (Moneyball)
    if 'Bargain Hunting (ROI)' in priorities:
        base_perf = 0.5*normalize(df['overall']) + 0.5*normalize(df['potential'])
        roi = base_perf / (normalize(df['value_eur']) + 0.01)
        df['Scout_Score'] += normalize(roi) * 3.0 

    # 6. PACE (Speed Demons)
    if 'Pace & Speed' in priorities:
        df['Scout_Score'] += normalize(df.get('pace', 0)) * 2.0
        
    # 7. MARKET HYPE (Galacticos)
    if 'Star Power (Marketability)' in priorities:
        df['Scout_Score'] += normalize(df.get('international_reputation', 0)) * 1.5 + normalize(df['overall']) * 1.5

    # Normalize final score 0-100
    df['Scout_Score'] = normalize(df['Scout_Score']) * 100
    return df

# ==========================================
# 3. SIDEBAR: THE "GM" OFFICE
# ==========================================
df_raw = load_data()

if df_raw.empty:
    st.stop()

st.sidebar.title("👔 GM Office")
st.sidebar.markdown("Define your team identity.")

# A. Season & Budget
if 'season' in df_raw.columns:
    seasons = sorted(df_raw['season'].unique(), reverse=True)
    season = st.sidebar.selectbox("Season", seasons)
    df = df_raw[df_raw['season'] == season].copy()
else:
    df = df_raw.copy()

budget_m = st.sidebar.slider("Transfer Budget (€M)", 50, 500, 150)

# B. The Priority Selector
st.sidebar.divider()
st.sidebar.subheader("🎯 Scouting Priorities")
priority_options = [
    'Scoring Efficiency', 'Playmaking & Assists', 'Defensive Solidity', 
    'Future Potential', 'Bargain Hunting (ROI)', 'Pace & Speed', 'Star Power (Marketability)'
]
selected_priorities = st.sidebar.multiselect(
    "Select 3 Priorities:", priority_options, 
    default=['Scoring Efficiency', 'Bargain Hunting (ROI)', 'Defensive Solidity'], max_selections=3
)

if len(selected_priorities) < 3:
    st.sidebar.warning("⚠️ Please select 3 priorities to activate the algorithm.")
    st.stop()

# ==========================================
# 4. ALGORITHM & DRAFTING
# ==========================================
df_scored = calculate_custom_score(df, selected_priorities)
df_pool = df_scored.sort_values(by='Scout_Score', ascending=False)

def draft_player(pool, pos, exclude_names, max_cost):
    candidates = pool[
        (pool['Pos_Group'] == pos) & 
        (~pool['short_name'].isin(exclude_names)) & 
        (pool['value_eur'] <= max_cost)
    ]
    if candidates.empty: return None
    return candidates.iloc[0]

squad, squad_names = [], []
remaining_budget = budget_m * 1000000
requirements = [('FWD', 3), ('MID', 3), ('DEF', 4), ('GK', 1)]

for pos, count in requirements:
    for _ in range(count):
        # Dynamic budget allocation heuristic
        pick = draft_player(df_pool, pos, squad_names, remaining_budget * 0.45) 
        if pick is not None:
            squad.append(pick)
            squad_names.append(pick['short_name'])
            remaining_budget -= pick['value_eur']

squad_df = pd.DataFrame(squad)

# ==========================================
# 5. MAIN DASHBOARD VISUALS
# ==========================================
st.title(f"🏆 Your 'Moneyball' Dream Team")
st.markdown(f"**Strategy:** {' + '.join(selected_priorities)}")

if squad_df.empty:
    st.error("Could not draft a full team with the current budget constraints. Try increasing the budget.")
    st.stop()

# KPIs
col1, col2, col3, col4 = st.columns(4)
total_cost = squad_df['value_eur'].sum()
col1.metric("Total Spent", f"€{total_cost/1e6:.1f}M", delta=f"{remaining_budget/1e6:.1f}M Saved")
col2.metric("Team Scout Score", f"{squad_df['Scout_Score'].mean():.1f}", "/ 100")
col3.metric("Average Age", f"{squad_df['age_fifa'].mean():.1f}", "Years")
col4.metric("Star Player", squad_df.loc[squad_df['Scout_Score'].idxmax()]['short_name'])

# --- TABS ---
tab1, tab2, tab3, tab4 = st.tabs(["⚽ Formation", "🔎 Skill Analysis", "📊 Market Efficiency", "📋 Full Roster"])

# --- TAB 1: PITCH ---
with tab1:
    def create_pitch(team):
        fig = go.Figure()
        # Green Pitch
        fig.add_shape(type="rect", x0=0, y0=0, x1=100, y1=100, line=dict(color="white"), fillcolor="#1e7e34", layer="below")
        # Center Line
        fig.add_shape(type="line", x0=50, y0=0, x1=50, y1=100, line=dict(color="white", width=2))
        # Center Circle
        fig.add_shape(type="circle", x0=40, y0=40, x1=60, y1=60, line=dict(color="white", width=2))
        
        # 4-3-3 Coordinates (Horizontal view 0-100)
        coords = {
            'GK': [(10, 50)], 
            'DEF': [(30, 20), (30, 40), (30, 60), (30, 80)], # LB, CB, CB, RB
            'MID': [(55, 30), (50, 50), (55, 70)],           # LCM, CDM, RCM
            'FWD': [(80, 20), (85, 50), (80, 80)]            # LW, ST, RW
        }
        
        for pos_grp, xy_list in coords.items():
            players = team[team['Pos_Group'] == pos_grp]
            for i, (x, y) in enumerate(xy_list):
                if i < len(players):
                    p = players.iloc[i]
                    fig.add_trace(go.Scatter(
                        x=[x], y=[y], mode='markers+text',
                        marker=dict(size=25, color='white', line=dict(width=2, color='black')),
                        text=[f"<b>{p['short_name']}</b><br><span style='font-size:10px'>{int(p['overall'])}</span>"],
                        textposition="top center", hoverinfo='text',
                        hovertext=f"Name: {p['short_name']}<br>€{p['value_eur']/1e6:.1f}M<br>Score: {p['Scout_Score']:.1f}"
                    ))
        
        fig.update_xaxes(showgrid=False, visible=False, range=[0, 100])
        fig.update_yaxes(showgrid=False, visible=False, range=[0, 100])
        fig.update_layout(height=600, margin=dict(l=10,r=10,t=10,b=10), paper_bgcolor="#0e1117", plot_bgcolor="#0e1117", showlegend=False)
        return fig
        
    st.plotly_chart(create_pitch(squad_df), use_container_width=True)

# --- TAB 2: SKILL COMPARISON ---
with tab2:
    st.markdown("### 🧬 Top 10 Comparison Matrix")
    c1, c2 = st.columns([1, 3])
    
    with c1:
        analyze_pos = st.selectbox("Select Position to Analyze", ['FWD', 'MID', 'DEF', 'GK'])
        top_10 = df_pool[df_pool['Pos_Group'] == analyze_pos].head(10).copy()
        compare_player_name = st.selectbox("Compare Player:", top_10['short_name'])
        
    with c2:
        metrics = ['pace', 'shooting', 'passing', 'dribbling', 'defending', 'physic']
        
        if not top_10.empty:
            # Stats for selected player
            player_stats = top_10[top_10['short_name'] == compare_player_name][metrics].iloc[0].values
            # Stats for Avg
            avg_stats = top_10[metrics].mean().values
            
            fig_radar = go.Figure()
            fig_radar.add_trace(go.Scatterpolar(
                r=avg_stats, theta=metrics, fill='toself', name='Top 10 Average',
                line_color='gray', opacity=0.4
            ))
            fig_radar.add_trace(go.Scatterpolar(
                r=player_stats, theta=metrics, fill='toself', name=compare_player_name,
                line_color='#00CC96', opacity=0.8
            ))
            fig_radar.update_layout(
                polar=dict(radialaxis=dict(visible=True, range=[0, 100])),
                title=f"Head-to-Head: {compare_player_name} vs Top 10 Avg",
                height=400, template="plotly_dark",
                paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)"
            )
            st.plotly_chart(fig_radar, use_container_width=True)

    st.markdown("---")
    st.markdown("#### 📏 The 'Skill Gap' (Parallel Coordinates)")
    
    if not top_10.empty:
        fig_par = px.parallel_coordinates(
            top_10, 
            dimensions=['overall', 'pace', 'shooting', 'passing', 'dribbling', 'defending', 'physic'],
            color="Scout_Score", 
            color_continuous_scale=px.colors.diverging.Tealrose,
            labels={k:k.capitalize() for k in metrics},
            title=f"Top 10 {analyze_pos} Candidates: Attribute Flow"
        )
        st.plotly_chart(fig_par, use_container_width=True)


# --- TAB 3: MARKET ---
with tab3:
    st.markdown("#### Are you beating the market?")
    fig_scatter = px.scatter(
        df_scored[df_scored['value_eur'] > 0],
        x="value_eur", y="Scout_Score", color="Pos_Group",
        log_x=True, hover_name="short_name", title="Entire Market vs Your Team",
        color_discrete_map={'FWD': '#EF553B', 'MID': '#00CC96', 'DEF': '#AB63FA', 'GK': '#FFA15A'}
    )
    fig_scatter.add_trace(go.Scatter(
        x=squad_df['value_eur'], y=squad_df['Scout_Score'],
        mode='markers', marker=dict(size=15, color='white', symbol='star'), name="Your Team"
    ))
    st.plotly_chart(fig_scatter, use_container_width=True)

# --- TAB 4: ROSTER ---
with tab4:
    display_df = squad_df[['Pos_Group', 'short_name', 'club_name', 'age_fifa', 'overall', 'potential', 'value_eur', 'Scout_Score']].copy()
    display_df['value_eur'] = display_df['value_eur'].apply(lambda x: f"€{x/1e6:.1f}M")
    display_df['Scout_Score'] = display_df['Scout_Score'].round(1)
    st.dataframe(display_df, hide_index=True)
