"""Rietveld-style two-phase refinement for the TCB MgFeO XRD patterns.

Full-pattern (Rietveld-style) refinement against ideal-structure reflection
tables in ``reflections.json``. Phases: hematite (alpha-Fe2O3), magnesioferrite
spinel (MgFe2O4), optional periclase (MgO).

Model: pseudo-Voigt peaks (Thompson-Cox-Hastings Cu K-alpha1/2 doublets),
Caglioti FWHM(2-theta), Chebyshev background, per-phase lattice parameters and
zero shift. Phase scales + background solved by linear least squares inside
each nonlinear step (variable projection); scales constrained non-negative.

Run from the ``tcb/`` directory:  python rietveld/rietveld_tcb.py
"""
from pathlib import Path
import json
import zipfile
import xml.etree.ElementTree as ET

import numpy as np
from scipy.optimize import least_squares, nnls
from scipy.ndimage import minimum_filter1d, uniform_filter1d
import matplotlib.pyplot as plt

LAM1, LAM2, RATIO = 1.540598, 1.544419, 0.5
N_BG = 6
REFL_PATH = Path(__file__).with_name("reflections.json")

def load_reflections():
    with open(REFL_PATH) as f:
        return json.load(f)

def load_brml(path):
    with zipfile.ZipFile(path) as zf:
        root = ET.fromstring(zf.read("Experiment0/RawData0.xml"))
    d = np.array([[float(v) for v in x.text.split(",")] for x in root.iter("Datum")])
    o = np.argsort(d[:, 2])
    tt, ii = d[o, 2], d[o, 4]
    keep = np.concatenate(([True], np.diff(tt) > 1e-6))
    return tt[keep], ii[keep]

def two_theta(hkl, lam, phase, a, c):
    hkl = np.atleast_2d(hkl)
    if phase["hexagonal"]:
        h, k, l = hkl[:, 0], hkl[:, 1], hkl[:, 2]
        s = lam * np.sqrt(4.0 / 3.0 * (h * h + h * k + k * k) / a ** 2 + l * l / c ** 2) / 2
    else:
        s = lam * np.sqrt(np.sum(hkl ** 2, axis=1)) / (2 * a)
    return np.degrees(2 * np.arcsin(np.clip(s, -1, 1)))

def pseudo_voigt(x, x0, fwhm, eta):
    fwhm = np.maximum(fwhm, 1e-4)
    lor = 1.0 / (1.0 + ((x - x0) / (fwhm / 2)) ** 2)
    gau = np.exp(-((x - x0) ** 2) / (2 * (fwhm / 2.35482) ** 2))
    return eta * lor + (1 - eta) * gau

def phase_column(tt, phase, cell, zero, fwhm, eta):
    hkl, I = np.asarray(phase["hkl"]), np.asarray(phase["I"])
    a, c = cell
    col = np.zeros_like(tt)
    for lam, ratio in ((LAM1, 1.0), (LAM2, RATIO)):
        for x0, inten in zip(two_theta(hkl, lam, phase, a, c), I):
            col += ratio * inten * pseudo_voigt(tt, x0 + zero, fwhm, eta)
    return col

def cheb_basis(tt, n=N_BG):
    xn = (tt - tt.min()) / (tt.max() - tt.min()) * 2 - 1
    return np.column_stack(
        [np.polynomial.chebyshev.chebval(xn, np.eye(n)[k]) for k in range(n)])

def estimate_background(tt, ii, window=61):
    bg = uniform_filter1d(minimum_filter1d(ii, window), window)
    k = np.ones(window) / window
    pad = np.pad(bg, window, mode="edge")
    return np.convolve(pad, k, mode="same")[window:window + len(tt)]

class Rietveld:
    """Nonlinear parameters q (per phase set):

    [a_0, (c_0), a_1, (c_1), ..., zero, U, V, W, eta0, eta1]
    Hexagonal phases get (a, c); cubic phases get (a,).
    """

    def __init__(self, tt, ii, phases):
        self.tt, self.ii = tt, ii
        self.phases = phases
        self.bg = estimate_background(tt, ii)
        self.sigma = np.sqrt(np.maximum(ii, 1.0))
        self.wsig = 1.0 / self.sigma
        self.slices = []
        off = 0
        for p in phases:
            n = 2 if p["hexagonal"] else 1
            self.slices.append(slice(off, off + n))
            off += n
        self.n_cell = off

    def cells(self, q):
        out = []
        for s, p in zip(self.slices, self.phases):
            v = q[s]
            out.append((v[0], v[1]) if p["hexagonal"] else (float(v[0]), None))
        return out

    def basis(self, q):
        zero = q[self.n_cell]
        U, V, W, eta0, eta1 = q[self.n_cell + 1:]
        tan = np.tan(np.radians(self.tt / 2))
        fwhm = np.sqrt(np.maximum(U * tan ** 2 + V * tan + W, 1e-8))
        eta = np.clip(eta0 + eta1 * self.tt / 100, 0, 0.9)
        cols = [phase_column(self.tt, p, cell, zero, fwhm, eta)
                for p, cell in zip(self.phases, self.cells(q))]
        return np.column_stack(cols + [cheb_basis(self.tt)])

    def solve_linear(self, q):
        A = self.basis(q)
        Aw = A * self.wsig[:, None]
        bw = self.ii * self.wsig
        nph = len(self.phases)
        coef = np.linalg.lstsq(Aw, bw, rcond=None)[0]
        if np.any(coef[:nph] < 0):
            bgc = coef[nph:]
            x, _ = nnls(Aw[:, :nph], bw - Aw[:, nph:] @ bgc)
            coef = np.concatenate([x, bgc])
        return coef, A @ coef

    def refine(self, max_nfev=2000):
        def resid(q):
            _, ycalc = self.solve_linear(q)
            return (ycalc - self.ii) / self.sigma

        q0, lo, hi = [], [], []
        for p in self.phases:
            q0.append(p["a0"]); lo.append(p["a0"] - 0.06); hi.append(p["a0"] + 0.06)
            if p["hexagonal"]:
                q0.append(p["c0"]); lo.append(p["c0"] - 0.15); hi.append(p["c0"] + 0.15)
        q0 += [0.0, 0.05, -0.02, 0.04, 0.5, 0.0]
        lo += [-0.3, 0.0, -0.4, 0.005, 0.0, -0.3]
        hi += [0.3, 0.4, 0.0, 0.150, 0.9, 0.3]
        q0, lo, hi = map(np.asarray, (q0, lo, hi))

        # stage 1: cells + zero, then stage 2: everything
        for idx in (list(range(self.n_cell + 1)), list(range(len(q0)))):
            free = np.zeros(len(q0), bool); free[idx] = True
            l = np.where(free, lo, q0 - 1e-12)
            h = np.where(free, hi, q0 + 1e-12)
            r = least_squares(resid, q0, bounds=(l, h),
                              max_nfev=600 if idx[0] == 0 else max_nfev,
                              diff_step=1e-6)
            q0 = r.x
        self.q = q0
        self.coef, self.ycalc = self.solve_linear(q0)
        self.rwp = np.sqrt(np.sum(((self.ii - self.ycalc) / self.sigma) ** 2)
                           / np.sum((self.ii / self.sigma) ** 2)) * 100
        return self

    def weight_fractions(self):
        wts = {}
        for k, p in enumerate(self.phases):
            a, c = self.cells(self.q)[k]
            vol = (np.sqrt(3) / 2 * a ** 2 * c) if p["hexagonal"] else a ** 3
            zmv = p["Z"] * p["mass"] * vol * 1.66054
            wts[p["name"]] = self.coef[k] * np.sum(p["I"]) * zmv
        tot = sum(wts.values())
        return {k: 100 * v / tot for k, v in wts.items()}

    def report(self):
        zero = self.q[self.n_cell]
        U, V, W, eta0, eta1 = self.q[self.n_cell + 1:]
        lines = [f"Rwp = {self.rwp:.2f}%"]
        for p, cell in zip(self.phases, self.cells(self.q)):
            a, c = cell
            lines.append(f"  {p['name']:28s} a = {a:.4f} A"
                         + (f", c = {c:.4f} A" if c else ""))
        for name, wt in self.weight_fractions().items():
            lines.append(f"  wt% {name:33s} {wt:5.1f}")
        lines.append(f"  zero shift = {zero:+.3f} deg | Caglioti U = {U:.3f}, "
                     f"V = {V:.3f}, W = {W:.4f} | eta = {eta0:.2f}{eta1:+.2f}*2th/100")
        return "\n".join(lines)

def refine_pattern(tag, brml_path, phases=("hematite", "spinel")):
    refl = load_reflections()
    tt, ii = load_brml(brml_path)
    m = (tt >= 15) & (tt <= 80)
    R = Rietveld(tt[m], ii[m], [refl[k] for k in phases]).refine()
    print(f"== {tag}: phases = {', '.join(phases)}")
    print(R.report())
    return R

def plot(R, tag, ax=None):
    if ax is None:
        _, ax = plt.subplots(figsize=(11, 4.5))
    ax.plot(R.tt, R.ii, lw=0.6, color="k", label="observed")
    ax.plot(R.tt, R.ycalc, lw=1.0, color="C1", label="calculated")
    nph = len(R.phases)
    for k, p in enumerate(R.phases):
        col = R.basis(R.q)[:, k] * R.coef[k]
        ax.plot(R.tt, col + R.ycalc - R.basis(R.q)[:, nph:] @ R.coef[nph:],
                lw=0.7, alpha=0.6, label=p["name"])
    ax.plot(R.tt, (R.ii - R.ycalc) + R.ii.max() * 0.0 - 0.15 * R.ii.max(),
            lw=0.5, color="C3", alpha=0.6)
    ax.set_xlabel(r"2$\theta$ (degrees)")
    ax.set_ylabel("Intensity (counts)")
    ax.set_title(f"{tag} — Rietveld fit (Rwp = {R.rwp:.2f}%)")
    ax.legend(fontsize=8)
    return ax

if __name__ == "__main__":
    here = Path(__file__).resolve().parent.parent
    for tag, rel in [("MG_AS", "XRay/MG_AS.brml"), ("MgFeO4", "Xray2/MgFeO4.brml")]:
        R = refine_pattern(tag, here / rel)
        fig, ax = plt.subplots(figsize=(11, 4.5))
        plot(R, tag, ax)
        fig.tight_layout()
        out = here / "rietveld" / f"fit_{tag}.png"
        fig.savefig(out, dpi=150)
        print(f"  plot -> {out}")
