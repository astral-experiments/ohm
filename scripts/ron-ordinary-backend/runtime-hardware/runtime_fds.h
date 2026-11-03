#pragma once
static constexpr int role_count=15;
static constexpr int serde_role=12, contact_role=13, crypto_role=14, vg_role=-1;
static constexpr int role_fd(int role) {return role<3?190+role:200+role-3;}
