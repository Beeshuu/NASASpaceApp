/**
 * Auth0 Action, trigger: Login / Post Login. Paste into Actions > Library > Build Custom, then Deploy
 * and add it to the Post Login trigger (PROGRESS.md, phase 13, Auth0 step 9).
 *
 * Puts the user's one Vital Orbit role, and a crew member's crew id, into the ID token. Cloudflare Access
 * copies both claims into its JWT under `custom`, where the Worker reads them (src/auth.py).
 */
exports.onExecutePostLogin = async (event, api) => {
  const ns = 'https://vitalorbit.health/'
  const roles = (event.authorization?.roles ?? []).filter((r) => ['crew', 'flight_surgeon', 'commander'].includes(r))
  if (roles.length !== 1) {
    return api.access.deny('This account needs exactly one Vital Orbit role: crew, flight_surgeon or commander.')
  }
  api.idToken.setCustomClaim(`${ns}role`, roles[0])
  if (roles[0] === 'crew') {
    const crewId = event.user.app_metadata?.crew_id
    if (!crewId) return api.access.deny('This crew account has no crew_id in its app_metadata.')
    api.idToken.setCustomClaim(`${ns}crew_id`, crewId)
  }
}
