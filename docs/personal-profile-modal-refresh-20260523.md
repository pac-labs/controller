# Personal profile modal refresh — 2026-05-23

The personal profile / My Access modal now behaves like a coherent user settings workspace rather than a stack of loosely related cards.

## Design intent

The modal should communicate that PAC has one directory-backed user profile. The user should move between related areas of that profile without losing context.

## Layout

The modal is organized as:

- header with avatar, title, and close action
- left identity rail with the current principal and section navigation
- focused content panel for the selected section

Sections:

- Overview: username, display name, email
- Access: directory groups and usable platform resources
- Credentials: personal tokens; tokens identify the user only
- PAC RAM: personal memory bundle
- Preferences: advanced JSON preferences

## Rule retained

Credentials answer **who you are**. Directory groups answer **what you are allowed to do**.

## Files

- `pi_agent_platform/web/app/personal_settings.js`
- `pi_agent_platform/web/styles/personal-settings.css`
- `pi_agent_platform/web/styles.css`
