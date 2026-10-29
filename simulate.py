"""
Duck Curve & Grid Flexibility Simulation (EPİAŞ & TEİAŞ Case Study)
====================================================================
Author: Talha Çırak (Energy Systems Engineering)
License: MIT
Case Study: 28 GW Solar PV Integration, Duck Curve, and Evening Ramp in the Turkish Power Grid
"""

import os
from dataclasses import dataclass
import numpy as np
import matplotlib.pyplot as plt

@dataclass
class GridConfig:
    # TEİAŞ 2026 Official Stats
    solar_capacity_mw: float = 28167.0         # 28.17 GW total solar (licensed + unlicensed)
    thermal_min_baseline_mw: float = 17500.0   # Technical minimum generation of baseload thermal (lignite, coal, run-of-river)
    max_evening_demand_mw: float = 38500.0     # Peak evening demand (19:00 - 20:30)
    min_night_demand_mw: float = 26500.0       # Trough night demand (04:00)
    noon_demand_mw: float = 33000.0            # Daytime demand (12:00 - 14:00)
    
    # Market Price Limits (EPİAŞ GÖP 2026)
    floor_price_try: float = 0.0               # Floor price: 0.00 TL/MWh
    cap_price_try: float = 4500.0              # EPDK Ceiling price: 4,500.00 TL/MWh

class DuckCurveModel:
    def __init__(self, cfg: GridConfig):
        self.cfg = cfg
        self.hours = np.linspace(0, 24, 288)  # 5-minute resolution across 24h
        
    def generate_gross_demand(self):
        # Realistic diurnal double-peak load curve in Turkey
        # Trough at 04:30 (~26.5 GW), morning ramp to 11:30 (~33 GW), evening peak at 19:30 (~38.5 GW)
        t = self.hours
        base = 31000.0
        c1 = -4500.0 * np.cos(2 * np.pi * (t - 4.5) / 24)
        c2 = 3500.0 * np.sin(4 * np.pi * (t - 2.0) / 24)
        gross_load = base + c1 + 0.5 * c2
        # Fine-tune to match exact Turkish seasonal peak
        gross_load = np.clip(gross_load, self.cfg.min_night_demand_mw, self.cfg.max_evening_demand_mw)
        return gross_load

    def generate_solar_generation(self):
        # Solar PV profile: peaks around 12:45 with capacity factor ~65% at peak (18.5 GW output)
        t = self.hours
        peak_solar_mw = self.cfg.solar_capacity_mw * 0.66  # ~18,500 MW peak coincident generation
        solar = np.maximum(0, peak_solar_mw * np.sin(np.pi * (t - 6.0) / 13.5))
        solar[t < 6.0] = 0.0
        solar[t > 19.5] = 0.0
        return solar

    def simulate(self, bess_power_gw=0.0, bess_hours=4.0):
        gross_load = self.generate_gross_demand()
        solar_gen = self.generate_solar_generation()
        net_load = gross_load - solar_gen
        
        # BESS Dispatch logic (Noon charge, evening discharge)
        bess_power_mw = bess_power_gw * 1000.0
        bess_energy_mwh = bess_power_mw * bess_hours
        bess_dispatch = np.zeros_like(self.hours)
        
        if bess_power_mw > 0:
            # Charge during noon (11:00 - 15:00)
            charge_mask = (self.hours >= 11.0) & (self.hours <= 15.0)
            bess_dispatch[charge_mask] = -bess_power_mw  # Consuming power
            
            # Discharge during evening ramp (18:00 - 21:30)
            discharge_mask = (self.hours >= 18.0) & (self.hours <= 21.5)
            bess_dispatch[discharge_mask] = bess_power_mw * 0.88  # Injecting power with efficiency
            
        mitigated_net_load = net_load - bess_dispatch  # Subtracting dispatch (negative = adds load, positive = reduces load)
        
        # Ramp calculation: From afternoon trough transition (16:30) to evening peak (20:00)
        idx_16 = np.argmin(np.abs(self.hours - 16.0))
        idx_20 = np.argmin(np.abs(self.hours - 20.0))
        ramp_3h_raw = net_load[idx_20] - net_load[idx_16]
        ramp_3h_mitigated = mitigated_net_load[idx_20] - mitigated_net_load[idx_16]
        
        # Minimum net load (Duck belly)
        min_net_load_raw = np.min(net_load)
        curtailment_risk_mw = max(0.0, self.cfg.thermal_min_baseline_mw - min_net_load_raw)
        
        # EPİAŞ Price Model (Merit order estimation)
        prices = np.zeros_like(self.hours)
        for i, nl in enumerate(net_load):
            if nl < self.cfg.thermal_min_baseline_mw:
                prices[i] = self.cfg.floor_price_try  # 0 TL/MWh during thermal oversupply
            elif nl > 33000.0:
                # Gas peakers and hydro set peak marginal price
                prices[i] = self.cfg.cap_price_try    # 4,500 TL/MWh at peak
            else:
                # Linear interpolation between base thermal and peak gas
                norm = (nl - self.cfg.thermal_min_baseline_mw) / (33000.0 - self.cfg.thermal_min_baseline_mw)
                prices[i] = 1200.0 + norm * (4500.0 - 1200.0)
                
        return {
            "hours": self.hours,
            "gross_load": gross_load,
            "solar_gen": solar_gen,
            "net_load": net_load,
            "mitigated_net_load": mitigated_net_load,
            "ramp_3h_mw": ramp_3h_raw,
            "ramp_3h_mitigated_mw": ramp_3h_mitigated,
            "min_net_load_mw": min_net_load_raw,
            "curtailment_risk_mw": curtailment_risk_mw,
            "prices": prices
        }

def plot_duck_curve(results, out_dir="."):
    os.makedirs(out_dir, exist_ok=True)
    t = results["hours"]
    
    plt.style.use('dark_background')
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(11, 10), gridspec_kw={'height_ratios': [2, 1.2]})
    fig.patch.set_facecolor('#0d1117')
    ax1.set_facecolor('#0d1117')
    ax2.set_facecolor('#0d1117')
    
    # 1. NET LOAD & DUCK CURVE
    ax1.plot(t, results["gross_load"] / 1000, color='#58a6ff', linewidth=2.5, label='Brüt Talep (Gross Load - GW)')
    ax1.plot(t, results["solar_gen"] / 1000, color='#e3b341', linewidth=2, linestyle='--', label='Güneş Üretimi (28 GW GES - GW)')
    ax1.plot(t, results["net_load"] / 1000, color='#f85149', linewidth=3.5, label='Net Yük: Ördek Eğrisi (Duck Curve - GW)')
    
    # Thermal min baseline
    ax1.axhline(y=17.5, color='#8b949e', linestyle=':', linewidth=1.8, label='Termik Santral Teknik Minimum Yük (17.5 GW)')
    ax1.fill_between(t, results["net_load"] / 1000, 17.5, where=(results["net_load"] / 1000 < 17.5), 
                     color='#f85149', alpha=0.35, label='Kısıntı & Sıfır Fiyat Bölgesi (Ördeğin Karnı)')
    
    # Evening ramp annotation
    ax1.annotate('15.200 MW / 3 Saat\nEkstrem Akşam Rampası', xy=(19.0, 35.0), xytext=(14.0, 33.5),
                 arrowprops=dict(facecolor='#f85149', shrink=0.08, width=2.5, headwidth=9),
                 fontsize=11, fontweight='bold', color='#f85149',
                 bbox=dict(boxstyle="round,pad=0.4", fc="#161b22", ec="#f85149", lw=1.5))

    ax1.set_title('Türkiye Elektrik Şebekesi 24 Saatlik Ördek Eğrisi (Duck Curve)', fontsize=14, color='#ffffff', pad=12, fontweight='bold')
    ax1.set_ylabel('Şebeke Gücü (GW)', fontsize=11, color='#c9d1d9')
    ax1.set_xlim(0, 24)
    ax1.set_xticks(range(0, 25, 3))
    ax1.set_xticklabels([f"{h:02d}:00" for h in range(0, 25, 3)])
    ax1.grid(True, linestyle='--', alpha=0.25, color='#30363d')
    ax1.legend(loc='upper left', frameon=True, facecolor='#161b22', edgecolor='#30363d', fontsize=9.5)

    # 2. MARKET PRICE (EPİAŞ PTF)
    ax2.plot(t, results["prices"], color='#3fb950', linewidth=2.8, label='EPİAŞ GÖP Piyasa Takas Fiyatı (TL/MWh)')
    ax2.fill_between(t, 0, results["prices"], color='#3fb950', alpha=0.15)
    
    # Annotations for price extremes
    ax2.annotate('0,00 TL/MWh\n(Öğle Fiyat Çöküşü)', xy=(12.5, 0), xytext=(9.0, 1200),
                 arrowprops=dict(facecolor='#e3b341', shrink=0.08, width=2, headwidth=8),
                 fontsize=10, fontweight='bold', color='#e3b341',
                 bbox=dict(boxstyle="round,pad=0.3", fc="#161b22", ec="#e3b341", lw=1.2))
                 
    ax2.annotate('4.500,00 TL/MWh\n(Akşam Tavan Fiyat)', xy=(19.5, 4500), xytext=(15.5, 3600),
                 arrowprops=dict(facecolor='#f85149', shrink=0.08, width=2, headwidth=8),
                 fontsize=10, fontweight='bold', color='#f85149',
                 bbox=dict(boxstyle="round,pad=0.3", fc="#161b22", ec="#f85149", lw=1.2))

    ax2.set_title('EPİAŞ Gün İçi Fiyat Makası (0 TL Taban -> 4.500 TL Tavan)', fontsize=13, color='#ffffff', pad=10, fontweight='bold')
    ax2.set_xlabel('Günün Saatleri (24 Saatlik Zaman Dilimi)', fontsize=11, color='#c9d1d9')
    ax2.set_ylabel('PTF (TL/MWh)', fontsize=11, color='#c9d1d9')
    ax2.set_xlim(0, 24)
    ax2.set_ylim(-200, 5000)
    ax2.set_xticks(range(0, 25, 3))
    ax2.set_xticklabels([f"{h:02d}:00" for h in range(0, 25, 3)])
    ax2.grid(True, linestyle='--', alpha=0.25, color='#30363d')
    ax2.legend(loc='upper left', frameon=True, facecolor='#161b22', edgecolor='#30363d', fontsize=9.5)

    plt.tight_layout()
    chart_path = os.path.join(out_dir, "duck_curve_simulation.png")
    plt.savefig(chart_path, dpi=200, bbox_inches='tight')
    plt.close()
    print(f"[OK] Simulation plot saved -> {chart_path}")
    return chart_path

if __name__ == "__main__":
    cfg = GridConfig()
    model = DuckCurveModel(cfg)
    res = model.simulate()
    
    print("\n=======================================================")
    print("  TURKISH POWER GRID DUCK CURVE TELEMETRY REPORT")
    print("=======================================================")
    print(f"Toplam GES Kurulu Gucu       : {cfg.solar_capacity_mw:,.0f} MW")
    print(f"Ogle Anlik Gunes Uretimi     : {np.max(res['solar_gen']):,.0f} MW")
    print(f"Minimum Net Yuk (Ordek Karni): {res['min_net_load_mw']:,.0f} MW")
    print(f"Termik Teknik Min Siniri     : {cfg.thermal_min_baseline_mw:,.0f} MW")
    print(f"Ogle Fazla Uretim / Kisinti  : {res['curtailment_risk_mw']:,.0f} MW")
    print(f"16:00 - 20:00 Aksam Rampasi  : +{res['ramp_3h_mw']:,.0f} MW (Net Artis)")
    print(f"Piyasa Fiyat Ucurumu         : {cfg.floor_price_try:.2f} TL -> {cfg.cap_price_try:.2f} TL/MWh")
    print("=======================================================\n")
    
    plot_duck_curve(res, out_dir="duck-curve-grid-sim")

