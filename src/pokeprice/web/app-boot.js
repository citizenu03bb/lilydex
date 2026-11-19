"use strict";
(async () => {
  try {
    const setup = await api("/setup");
    state.setup = setup.required;
    if (state.setup) {
      $("access-title").textContent = "Créer votre accès privé";
      $("access-help").textContent =
        "Choisissez votre compte administrateur pour commencer. Le mot de passe doit contenir au moins 10 caractères.";
      $("login-submit").textContent = "Créer mon compte";
      $("login-form").elements.password.autocomplete = "new-password";
      showAccess();
    } else {
      try {
        await showWorkspace(await api("/session"));
      } catch {
        showAccess();
      }
    }
  } catch (err) {
    showAccess();
    $("login-error").textContent = err.message;
  }
})();
