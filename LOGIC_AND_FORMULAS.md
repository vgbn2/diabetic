# Bio-Quant: Advanced Logic & Formulas Reference
## Comprehensive Technical Foundation

This document serves as the complete mathematical and physical reference for the **Bio-Quant** system. It covers everything from signal processing to the microwave physics of non-invasive sensing.

---

## 📡 1. DSP & SIGNAL ANALYSIS

### 1.1 Core Filtering (Kalman & Beyond)

#### Linear Kalman Filter (Core Engine)
- **State Vector (x):** $x = \begin{bmatrix} G & V \end{bmatrix}^T$
- **Transition Matrix (F):** $F = \begin{bmatrix} 1 & \Delta t \\ 0 & 1 \end{bmatrix}$
- **Update Logic:** $\hat{x}_k = \hat{x}_{k|k-1} + K_k(z_k - H\hat{x}_{k|k-1})$

#### Extended & Unscented Kalman (Nonlinear Dynamics)
- **EKF Jacobian:** $F_k = \left.\frac{\partial f}{\partial x}\right|_{\hat{x}_{k-1}}, H_k = \left.\frac{\partial h}{\partial x}\right|_{\hat{x}_{k|k-1}}$
- **UKF Sigma Points:** $\mathcal{X}_0 = \hat{x}, \mathcal{X}_i = \hat{x} \pm (\sqrt{(n+\lambda)P})_i$
*UKF is preferred for non-linear glucose dynamics without needing Jacobians.*

#### FIR & IIR Filtering
- **FIR (Trend):** $y[n] = \sum_{k=0}^{M} b_k \cdot x[n-k]$
- **IIR (Efficiency):** $y[n] = \sum_{k=0}^{M} b_k x[n-k] - \sum_{k=1}^{N} a_k y[n-k]$
- **Z-Transform:** $H(z) = \frac{\sum b_k z^{-k}}{1 + \sum a_k z^{-k}}$

---

### 1.2 Signal Analysis Metrics

- **FFT (Frequency Content):** $X[k] = \sum_{n=0}^{N-1} x[n]e^{-j2\pi kn/N}$
- **PSD (Dominant Frequencies):** $S_{xx}(f) = \lim_{T\to\infty} \frac{1}{T} |X(f)|^2$
- **SNR:** $10\log_{10}(P_{signal}/P_{noise})$ [dB]
- **Autocorrelation:** $R_{xx}(\tau) = \int x(t)x(t+\tau)dt$ (detects repeating glucose patterns)
- **Wavelet Transform:** $W(a,b) = \frac{1}{\sqrt{a}} \int x(t)\psi^*(\frac{t-b}{a})dt$ (best for non-stationary glucose signals)

---

## 🧬 2. BIOLOGICAL & FEATURE DYNAMICS

- **Velocity:** $V(t) = \frac{G(t) - G(t - \Delta t)}{\Delta t}$
- **Acceleration:** $A(t) = \frac{V(t) - V(t - \Delta t)}{\Delta t}$
- **30-Min Projection:** $\hat{G}(t+30) = G(t) + 30V(t) + \frac{1}{2}30^2 A(t)$
- **Bergman Minimal Model:**
  - $\frac{dG}{dt} = -p_1[G - G_b] - XG + p_1 G_b$
  - $\frac{dX}{dt} = -p_2 X + p_3[I - I_b]$

---

## 📻 3. MICROWAVE ENGINEERING (Non-Invasive Sensing)

### 3.1 Electromagnetics Foundation (Maxwell)
1. $\nabla \cdot \mathbf{E} = \frac{\rho}{\varepsilon_0}$ (Electric Gauss)
2. $\nabla \cdot \mathbf{B} = 0$ (Magnetic Gauss)
3. $\nabla \times \mathbf{E} = -\frac{\partial \mathbf{B}}{\partial t}$ (Faraday)
4. $\nabla \times \mathbf{B} = \mu_0\mathbf{J} + \mu_0\varepsilon_0\frac{\partial \mathbf{E}}{\partial t}$ (Ampere)

---

### 3.2 Sensor & Network Analysis

- **S11 (Reflection):** $S_{11} = \frac{Z_L - Z_0}{Z_L + Z_0}$
- **S21 (Transmission):** $S_{21} = \frac{2\sqrt{R_{in}R_{out}}}{Z_0}$
- **VSWR:** $\frac{1 + |S_{11}|}{1 - |S_{11}|}$ (Quality factor for sensor matching)

---

### 3.3 Tissue & Wave Interactions

- **Cole-Cole Model (Tissue Standard):** $\varepsilon^*(\omega) = \varepsilon_\infty + \sum_{n} \frac{\Delta\varepsilon_n}{1 + (j\omega\tau_n)^{1-\alpha_n}} - j\frac{\sigma_s}{\omega\varepsilon_0}$
- **Kramers-Kronig (Validity):** $\varepsilon'(\omega) = \varepsilon_\infty + \frac{2}{\pi} \mathcal{P} \int_0^\infty \frac{\omega' \varepsilon''(\omega')}{\omega'^2 - \omega^2} d\omega'$
- **Skin Depth ($\delta$):** $\delta = \frac{1}{\omega} \sqrt{\frac{2}{\mu\sigma}}$ (~2–4 cm at 2.4 GHz)
- **Reflections:** $\Gamma = \frac{\eta_2 - \eta_1}{\eta_2 + \eta_1}$ (where $\eta$ is wave impedance in tissue)

---

### 3.4 Antenna & Link Parameters

- **Resonant Frequency (CSRR):** $f_0 = \frac{1}{2\pi\sqrt{L_r C_r}}$
- **Aperture Area ($A_e$):** $A_e = \frac{\lambda^2 G}{4\pi}$
- **Far Field Boundary:** $r_{ff} = \frac{2D^2}{\lambda}$
- **SAR (Safety):** $SAR = \frac{\sigma |E|^2}{\rho}$ (FCC Limit: 1.6 W/kg)

---

## 🚀 4. MAPPING

1. **MW Sensor**: Detects $\Delta\varepsilon'$ via $\Delta f$ (Frequency Shift).
2. **DSP Logic**: Cleans signals via **UKF** and analyzes trends via **Wavelets**.
3. **ML Strategy**: Autocorrelation uncovers per-person circadian patterns $\to$ Personalized Input.
4. **Output**: Proactive (30-min lead) Hypo alert or Immediate Faint risk (Hyper + HRV drop).
