import numpy as np
import os

import healpy as hp
import pymaster as nmt

import utils
import masks
import maps


def main():
    #NSIDE = 2048
    NSIDE = 256

    G_max = 20.0
    fn_gaia = f'../data/gaia_G{G_max}.fits'
    fn_rand = f'../data/randoms/random_stardustm1064_G{G_max}_10x.fits'
    mask_names_gaia = ['mcs', 'dust']
    Av_max = 0.2
    #tag_Cls = '_prob'
    tag_Cls = '_ratio'
    fn_Cls = f'../data/Cls/Cls_G{G_max}_NSIDE{NSIDE}{tag_Cls}.npy'
    
    print(f"Computing lensing-QSO cross-correlation for QSOs with G<{G_max}, maps with NSIDE={NSIDE}")
    print(f"Will save Cls to {fn_Cls}")

    mask_k = get_planck_lensing_mask(NSIDE)
    map_k = get_planck_lensing_map(NSIDE)

    # prob:
    # mask_q_binary = get_qso_mask_binary(NSIDE, mask_names_gaia, Av_max=Av_max)
    # mask_q = get_qso_mask_prob(NSIDE, mask_q_binary)
    # map_q = get_qso_overdensity_map(NSIDE, fn_gaia, mask_q_binary)

    # ratio:
    mask_q_binary = get_qso_mask_binary(NSIDE, mask_names_gaia, Av_max=Av_max)
    map_q = get_qso_rand_overdensity_map(NSIDE, fn_gaia, fn_rand, mask_q_binary)

    # "We choose a conservative binning scheme with linearly spaced bins of
    # size ∆l = 50 starting from l_min = 25."
    ell_min = 25
    ell_max = 600
    ell_bin_width = 50
    bins = get_bins_linear(ell_min, ell_max, ell_bin_width)

    # signature: compute_Cls(bins, map1, map2, mask1, mask2)
    Cls_kk_obj = compute_Cls(bins, map_k, map_k, mask_k, mask_k)
    Cls_kq_obj = compute_Cls(bins, map_k, map_q, mask_k, mask_q)
    Cls_qq_obj = compute_Cls(bins, map_q, map_q, mask_q, mask_q)

    ell_arr = bins.get_effective_ells()
    Cl_objs = [Cls_kk_obj, Cls_kq_obj, Cls_qq_obj]
    # Can't save bins or Cl_objs objects - get error "TypeError: cannot pickle 'SwigPyObject' object"
    result = np.array([ell_arr, Cls_kk_obj[0], Cls_kq_obj[0], Cls_qq_obj[0]])
    np.save(fn_Cls, result)
    print(f"Saved Cls to {fn_Cls}")


#Data from https://pla.esac.esa.int/#cosmology, (cosmology tab then lensing tab)
#Details: https://wiki.cosmos.esa.int/planck-legacy-archive/index.php/Lensing
def get_planck_lensing_map(NSIDE, fn_lensing='../data/COM_Lensing_4096_R3.00/MV/dat_klm.fits',
                           lmax=4096, lmax_smooth='auto'):
    print("Getting Planck lensing map")
    # Guidance here from: https://zonca.dev/2020/09/planck-spectra-healpy.html
    alm_lensing = hp.read_alm(fn_lensing)

    if lmax_smooth == 'auto':
        lmax_smooth = 2*NSIDE 
        
    if lmax_smooth is not None:
        # not sure about this ??
        fl = np.ones(lmax)
        ls = np.arange(lmax)
        fl[ls > lmax_smooth] = 0
        alm_lensing = hp.almxfl(alm_lensing, fl)

    map_lensing = hp.alm2map(alm_lensing, nside=NSIDE, lmax=lmax)
    # can't figure out how to set lmin! but this fixes the scaling
    # should i mask and then smooth or vice versa??
    #if lmax_smooth is not None:
        #map_lensing = hp.smoothing(map_lensing, lmax=lmax_smooth)
    return map_lensing
    

def get_planck_lensing_mask(NSIDE, fn_mask='../data/COM_Lensing_4096_R3.00/mask.fits.gz',
                            aposize_deg=0.5):
    print("Getting Planck lensing mask")
    # Apodization: 0.5 deg = 30' (arcmin), used in Martin White paper
    mask_lensing = hp.read_map(fn_mask, dtype=bool)
    mask_lensing = hp.pixelfunc.ud_grade(mask_lensing, NSIDE)
    if aposize_deg is not None:
        mask_lensing = nmt.mask_apodization(mask_lensing, aposize_deg, apotype="C2")
    return mask_lensing


# TODO: maybe don't need to mask here bc we'll input the mask to the Cls?? 
# but this changes the mean, so maybe should first too, as it says in White paper?
# tho maybe cleaner way to do with healpy...
def get_qso_rand_overdensity_map(NSIDE, fn_gaia, fn_rand, mask_binary):
    print("WARNING: NOT SURE ABOUT COORD SYS HERE YET")
    print("Getting QSO overdensity map")

    tab_gaia = utils.load_table(fn_gaia)
    tab_rand = utils.load_table(fn_rand)

    map_nqso_gaia_celestial, _ = maps.get_map(NSIDE, tab_gaia['ra'], tab_gaia['dec'], null_val=0)
    map_nqso_rand_celestial, _ = maps.get_map(NSIDE, tab_rand['ra'], tab_rand['dec'], null_val=0)

    print(len(map_nqso_gaia_celestial))
    print(len(map_nqso_rand_celestial))
    
    map_nqso_gaia = rotate_celestial_to_galactic(map_nqso_gaia_celestial)
    map_nqso_rand = rotate_celestial_to_galactic(map_nqso_rand_celestial)

    # map_nqso_gaia = map_nqso_gaia[mask_binary]
    # map_nqso_rand = map_nqso_rand[mask_binary]

    # idx_keep_gaia = masks.subsample_mask_indices(tab_gaia['ra'], tab_gaia['dec'], mask_binary)
    # tab_gaia = tab_gaia[idx_keep_gaia]
    # idx_keep_rand = masks.subsample_mask_indices(tab_rand['ra'], tab_rand['dec'], mask_binary)
    # tab_rand = tab_rand[idx_keep_rand]


    #"The weighted random counts in each Healpix pixel then form the “random map”. The overdensity field is defined as the “LRG map” divided by the “random map”, normalized to mean density and mean subtracted." (White 2022)
    #TODO: figure out what to do about these zeros!
    map_ratio = map_nqso_gaia / map_nqso_rand
    idx_finite = mask_binary & np.isfinite(map_ratio)

    #map_ratio_unmasked = map_ratio[mask_binary]
    #idx_finite = np.isfinite(map_ratio_unmasked)

    mean = np.mean(map_ratio[idx_finite]) 

    map_overdensity = np.full(map_ratio.shape, hp.UNSEEN)
    map_overdensity[idx_finite] = map_ratio[idx_finite]/mean - 1

    # This is now another overdensity tho, maybe don't want this if have randoms??
    #map_overdensity[idx_finite] = map_ratio[idx_finite]/np.mean(map_ratio[idx_finite]) - 1
    return map_overdensity


def get_qso_mask_binary(NSIDE, mask_names_gaia, Av_max=None):
    qso_mask_binary_celestial = ~masks.get_qso_mask(NSIDE, mask_names_gaia, Av_max=Av_max)
    qso_mask_binary_galactic = rotate_celestial_to_galactic(qso_mask_binary_celestial)
    return qso_mask_binary_galactic.astype(bool)


def get_qso_overdensity_map(NSIDE, fn_gaia, mask_q_binary):
    print("Getting QSO overdensity map")
    tab_gaia = utils.load_table(fn_gaia)
    map_nqso_gaia_celestial, _ = maps.get_map(NSIDE, tab_gaia['ra'], tab_gaia['dec'], null_val=0)
    map_nqso_gaia_galactic = rotate_celestial_to_galactic(map_nqso_gaia_celestial)
    #only use unmasked areas to compute mean
    mean = np.mean(map_nqso_gaia_galactic[mask_q_binary]) 
    map_overdensity = map_nqso_gaia_galactic/mean - 1
    return map_overdensity


def rotate_celestial_to_galactic(map_celestial):
    r = hp.Rotator(coord=['C','G'])
    #map_galactic = r.rotate_map_pixel(map_celestial)
    map_galactic = r.rotate_map_pixel(map_celestial)
    return map_galactic


def get_qso_mask_prob(NSIDE, mask_binary=None):
    # for probability map
    map_names = ['dust', 'stars', 'm10']
    G_max = 20.0
    NSIDE_maxprob = 64
    if NSIDE > NSIDE_maxprob:
        # we can't make a probability map w a gaussian process finer than this
        # (memory issues, and likely noise)
        fn_prob = f"../data/maps/map_probability_{'_'.join(map_names)}_NSIDE{NSIDE_maxprob}_G{G_max}.fits"
        if not os.path.exists(fn_prob):
            raise ValueError(f"Probability map {fn_prob} doesn't exist!")
        map_prob = hp.read_map(fn_prob)
        map_prob = hp.ud_grade(map_prob, NSIDE)
    else:
        fn_prob = f"../data/maps/map_probability_{'_'.join(map_names)}_NSIDE{NSIDE}_G{G_max}.fits"
        if not os.path.exists(fn_prob):
            raise ValueError(f"Probability map {fn_prob} doesn't exist!")
        map_prob = hp.read_map(fn_prob)
    # combine prob w binary mask
    mask_prob = map_prob
    mask_prob_galactic = rotate_celestial_to_galactic(mask_prob)
    if mask_binary is not None:
        mask_prob_galactic[mask_binary==False] = 0.0 #nicer way to do this?
    return mask_prob_galactic


def get_mask_indices_keep(NSIDE, ra, dec, mask_names_gaia):
    b_max = 10
    Av_max = 0.2
    R = 3.1
    fn_dustmap = f'../data/maps/map_dust_NSIDE{NSIDE}.npy'
    # dict points to tuple with masks and extra args
    mask_gaia_dict = {'plane': (masks.galactic_plane_mask, [b_max]),
                  'mcs': (masks.magellanic_clouds_mask, []),
                  'dust': (masks.galactic_dust_mask, [Av_max, R, fn_dustmap])}

    idx_keep = np.full(len(ra),True)
    for mask_name in mask_names_gaia:
        mask_func, mask_func_args = mask_gaia_dict[mask_name]
        idx_keep_m = masks.subsample_by_mask(NSIDE, ra[idx_keep], dec[idx_keep], 
                                             mask_func, mask_func_args)
        idx_keep = idx_keep & idx_keep_m
    return idx_keep

## Compute pseudo-Cls
#Following https://arxiv.org/pdf/2111.09898.pdf and https://namaster.readthedocs.io/en/latest/sample_simple.html
def compute_Cls(bins, map1, map2, mask1, mask2):
    print("Computing Cls")
    field1 = nmt.NmtField(mask1, [map1])
    field2 = nmt.NmtField(mask2, [map2])
    Cls = nmt.compute_full_master(field1, field2, bins)
    return Cls


def get_bins_linear(ell_min, ell_max, ell_bin_width):
    ell_edges = np.arange(ell_min, ell_max+ell_bin_width, ell_bin_width)
    ell_ini = ell_edges[:-1]
    ell_end = ell_edges[1:]
    bins = nmt.NmtBin.from_edges(ell_ini, ell_end)
    return bins



if __name__=='__main__':
    main()
