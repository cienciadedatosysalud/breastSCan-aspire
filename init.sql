-- 1. Tabla Principal (Entidad Paciente)
CREATE TABLE women_ent (
    woman_id VARCHAR(255) PRIMARY KEY,
    birth_date_dt DATE,
    menarque_age_nm INTEGER,
    n_full_term_pregnancies_nm INTEGER,
    age_first_fullterm_pregnancy_nm INTEGER,
    breastfeeding_bl BOOLEAN,
    breastfeeding_nm INTEGER,
    menopause_cd INTEGER,
    menopause_age_nm INTEGER,
    menopause_cause_cd INTEGER,
    personal_cancer_history_cd INTEGER,
    breast_cancer_familial_atc_cd INTEGER,
    ovarian_cancer_familial_atc_cd INTEGER,
    surgical_atc_left_breast_cd INTEGER,
    surgical_atc_right_breast_cd INTEGER,
    hormonal_contraception_use_bl BOOLEAN,
    hormonal_contraception_duration_nm INTEGER,
    hormonal_replacement_therapy_bl BOOLEAN,
    hormonal_replacement_therapy_duration_nm INTEGER,
    histerectomy_bl BOOLEAN,
    height_nm INTEGER,
    weight_nm DOUBLE PRECISION,
    comorbidity_cardiovascular_disease_bl BOOLEAN,
    comorbidity_hypertension_bl BOOLEAN,
    comorbidity_diabetes_bl BOOLEAN,
    comorbidity_obesity_bl BOOLEAN,
    smoking_status_cd INTEGER,
    age_started_smoking_nm INTEGER,
    left_breast_pathology_atc_bl BOOLEAN,
    right_breast_pathology_atc_bl BOOLEAN,
    left_mammary_prosthesis_bl BOOLEAN,
    right_mammary_prosthesis_bl BOOLEAN,
    residence_local_administrative_unit_cd VARCHAR(255),
    genetic_testing_brca1_cd INTEGER,
    genetic_testing_brca2_cd INTEGER,
    genetic_testing_palb2_cd INTEGER,
    genetic_testing_check2_cd INTEGER,
    exitus_dt DATE
);

-- 2. Tabla DICOM Series
CREATE TABLE dicom_series_ent (
    woman_id VARCHAR(255),
    study_id VARCHAR(255),
    series_id VARCHAR(255),
    image_test_dt DATE,
    image_laterality_cd INTEGER,
    image_type_cd INTEGER,
    image_reason_cd INTEGER,
    healthcare_centre_cd VARCHAR(255),
    manufacturer_id VARCHAR(255),
    breast_density_cd INTEGER,
    birads_cd INTEGER,
    benign_lesion_cd INTEGER,
    malignant_lesion_cd INTEGER,
    lesion_location_cd INTEGER,
    lesion_size_nm DOUBLE PRECISION,
    lesion_mass_shape_cd INTEGER,
    lesion_mass_margin_cd INTEGER,
    lesion_associated_features_cd INTEGER,
    ct_cd INTEGER,
    cn_cd INTEGER,
    n_lesions_nm INTEGER,
    exploration_result_cd INTEGER,
    exploration_description_st TEXT, -- Usamos TEXT por si la descripción es larga
    PRIMARY KEY (woman_id, study_id, series_id),
    CONSTRAINT fk_dicom_woman FOREIGN KEY (woman_id) REFERENCES women_ent(woman_id) ON DELETE CASCADE
);

-- 3. Tabla Tratamiento Quirúrgico
CREATE TABLE surgical_treatment_ent (
    woman_id VARCHAR(255),
    initial_treatment_cd INTEGER,
    initial_treatment_code_st VARCHAR(255),
    initial_treatment_date_dt DATE,
    surgical_intervention_type_cd INTEGER,
    adyuvant_treatment_cd INTEGER,
    lymphovascular_invasion_bl BOOLEAN,
    number_lymph_nodes_examined_nm INTEGER,
    number_lymph_nodes_positive_nm INTEGER,
    PRIMARY KEY (woman_id, initial_treatment_date_dt), -- Clave compuesta para permitir múltiples tratamientos en fechas distintas
    CONSTRAINT fk_surgical_woman FOREIGN KEY (woman_id) REFERENCES women_ent(woman_id) ON DELETE CASCADE
);

-- 4. Tabla Muestras Patológicas (Biopsias)
CREATE TABLE pathological_specimen_ent (
    woman_id VARCHAR(255),
    biopsy_dt DATE,
    procedure_type_cd INTEGER,
    tumor_histotype_cd INTEGER,
    estrogen_receptors_perc_nm DOUBLE PRECISION,
    progesterone_receptors_perc_nm DOUBLE PRECISION,
    her2_ihc_status_bl BOOLEAN,
    her2_fish_positive_bl BOOLEAN,
    ki67_perc_nm DOUBLE PRECISION,
    intrinsic_subtype_cd INTEGER,
    breast_cancer_molecular_subtype_cd INTEGER,
    tumor_grade_cd INTEGER,
    tumor_stage_cd INTEGER,
    tumor_type_cd INTEGER,
    tumor_initial_t_stage_cd INTEGER,
    tumor_initial_n_stage_cd INTEGER,
    staging_cmetastasis_cd INTEGER,
    PRIMARY KEY (woman_id, biopsy_dt),
    CONSTRAINT fk_pathological_woman FOREIGN KEY (woman_id) REFERENCES women_ent(woman_id) ON DELETE CASCADE
);

-- 5. Tabla Tratamiento Neoadyuvante
CREATE TABLE neoadjuvant_treatment_ent (
    woman_id VARCHAR(255),
    neoadjuvant_therapy_drug_atc_cd VARCHAR(255),
    neoadjuvant_therapy_drug_rxnorm_cd VARCHAR(255),
    neoadjuvant_therapy_duration_nm INTEGER,
    drug_dosage_nm INTEGER,
    cumulative_drug_dosage_nm DOUBLE PRECISION,
    PRIMARY KEY (woman_id, neoadjuvant_therapy_drug_atc_cd), -- Clave compuesta por paciente y fármaco
    CONSTRAINT fk_neoadjuvant_woman FOREIGN KEY (woman_id) REFERENCES women_ent(woman_id) ON DELETE CASCADE
);

-- 6. Tabla de Seguimiento (Follow-up)
CREATE TABLE followup_ent (
    woman_id VARCHAR(255),
    neoadjuvant_therapy_response_mp_cd INTEGER,
    neoadjuvant_therapy_response_rcb_cd INTEGER,
    ypt_cd INTEGER,
    ypn_cd INTEGER,
    ypm_cd INTEGER,
    recurrence_date_dt DATE,
    recurrence_bl BOOLEAN,
    recurrence_site_cd INTEGER,
    last_followup_contact_dt DATE,
    PRIMARY KEY (woman_id, last_followup_contact_dt), -- Clave compuesta usando la fecha de contacto
    CONSTRAINT fk_followup_woman FOREIGN KEY (woman_id) REFERENCES women_ent(woman_id) ON DELETE CASCADE
);
